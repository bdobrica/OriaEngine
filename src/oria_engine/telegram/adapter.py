"""Private text ingress and plain-text egress; Telegram objects stay here."""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, TelegramObject, Update

from oria_engine.domain.channel import ChannelClient, ChannelMessage, reply_to_message
from oria_engine.observability import correlation_scope

logger = logging.getLogger(__name__)


def normalize_update(update: Update) -> ChannelMessage | None:
    message = update.message
    if (
        message is None
        or message.chat.type != ChatType.PRIVATE
        or message.from_user is None
        or message.from_user.is_bot
        or message.sender_chat is not None
        or message.business_connection_id is not None
        or message.text is None
    ):
        return None
    return ChannelMessage(
        provider="telegram",
        provider_user_id=str(message.from_user.id),
        provider_chat_id=str(message.chat.id),
        provider_message_id=str(message.message_id),
        provider_update_id=str(update.update_id),
        received_at=datetime.now(UTC),
        text=message.text,
    )


class TelegramChannelClient:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send_text(self, provider_chat_id: str, text: str) -> None:
        await self.bot.send_message(chat_id=int(provider_chat_id), text=text, parse_mode=None)


class PrivateMessageMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return None
        with correlation_scope(telegram_update_id=event.update_id):
            normalized = normalize_update(event)
            if normalized is None:
                return None
            data["channel_message"] = normalized
            try:
                result = await handler(event, data)
            except Exception:
                # Never pass aiogram exceptions (which can contain request bodies) to logging.
                logger.error("update_failed")
                return None
            logger.info("update_completed")
            return result


def create_dispatcher(client: ChannelClient) -> Dispatcher:
    dispatcher = Dispatcher(disable_fsm=True)
    dispatcher.update.outer_middleware(PrivateMessageMiddleware())
    router = Router(name="private_messages")

    @router.message(Command("start", "help"))
    async def command_handler(
        message: Message, channel_message: ChannelMessage, command: CommandObject
    ) -> None:
        await reply_to_message(channel_message, client, command=command.command)

    @router.message()
    async def fallback_handler(message: Message, channel_message: ChannelMessage) -> None:
        await reply_to_message(channel_message, client)

    dispatcher.include_router(router)
    return dispatcher
