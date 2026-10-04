"""Private text ingress and plain-text egress; Telegram objects stay here."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
    Update,
)

from oria_engine.db.repositories import UserUnavailableError
from oria_engine.domain.channel import ChannelButton, ChannelClient, ChannelMessage
from oria_engine.domain.consent import ConsentFlow
from oria_engine.observability import correlation_scope, count, measurement, observed
from oria_engine.queue.broker import Publisher
from oria_engine.queue.events import EventIngress
from oria_engine.queue.limits import AdmissionRejected

logger = logging.getLogger(__name__)
ALLOWED_UPDATES = ["message", "callback_query"]


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

    @observed("telegram_send")
    async def send_text(
        self, provider_chat_id: str, text: str, *, buttons: tuple[ChannelButton, ...] = ()
    ) -> None:
        markup = (
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=button.text, callback_data=button.data)]
                    for button in buttons
                ]
            )
            if buttons
            else None
        )
        await self.bot.send_message(
            chat_id=int(provider_chat_id), text=text, parse_mode=None, reply_markup=markup
        )


def normalize_callback(update: Update, bot_id: int) -> ChannelMessage | None:
    callback = update.callback_query
    if callback is None:
        return None
    message = callback.message
    if (
        not isinstance(message, Message)
        or message.chat.type != ChatType.PRIVATE
        or callback.from_user.is_bot
        or callback.from_user.id != message.chat.id
        or message.from_user is None
        or message.from_user.id != bot_id
        or message.business_connection_id is not None
        or callback.data is None
    ):
        return None
    return ChannelMessage(
        provider="telegram",
        provider_user_id=str(callback.from_user.id),
        provider_chat_id=str(message.chat.id),
        provider_message_id=str(message.message_id),
        provider_update_id=str(update.update_id),
        received_at=datetime.now(UTC),
        text="",
        callback_data=callback.data,
    )


class PrivateMessageMiddleware(BaseMiddleware):
    def __init__(self, *, webhook: bool = False) -> None:
        self.webhook = webhook

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return None
        with correlation_scope(telegram_update_id=event.update_id):
            normalized = normalize_update(event) or normalize_callback(event, data["bot"].id)
            if normalized is None:
                return None
            data["channel_message"] = normalized
            try:
                with measurement("telegram_update"):
                    result = await handler(event, data)
            except Exception:
                # Never pass aiogram exceptions (which can contain request bodies) to logging.
                logger.error("update_failed")
                if self.webhook:
                    raise
                return None
            logger.info("update_completed")
            return result


def create_dispatcher(
    client: ChannelClient,
    flow: ConsentFlow | None = None,
    *,
    ingress: EventIngress | None = None,
    publisher: Publisher | None = None,
    webhook: bool = False,
) -> Dispatcher:
    dispatcher = Dispatcher(disable_fsm=True)
    dispatcher.update.outer_middleware(PrivateMessageMiddleware(webhook=webhook))
    router = Router(name="private_messages")

    async def respond(channel_message: ChannelMessage, command: str | None = None) -> str | None:
        if ingress is not None:
            # aiogram acknowledges offsets even when a handler raises. Keep this update
            # in flight until PostgreSQL accepts it; shutdown cancellation still propagates.
            while True:
                try:
                    identifier = await ingress.accept(channel_message, command=command)
                    break
                except UserUnavailableError:
                    # A deleted account is a permanent rejection, not a database outage.
                    logger.info("update_completed")
                    return None
                except AdmissionRejected as exc:
                    count("inbound_limited")
                    logger.info("inbound_limited")
                    if not webhook and exc.reply:
                        await client.send_text(channel_message.provider_chat_id, exc.reply)
                    return exc.reply if webhook else None
                except Exception:
                    if webhook:
                        raise
                    logger.error("update_failed")
                    await asyncio.sleep(1)
            logger.info("job_admitted", extra={"job_id": identifier})
            if publisher is not None and await ingress.publishable(identifier):
                try:
                    await asyncio.to_thread(publisher.send, str(identifier))
                except Exception:
                    logger.warning("queue_unavailable")  # Durable worker scan closes enqueue gap.
                    if webhook:
                        raise
            return None
        assert flow is not None
        reply = await flow.handle(channel_message, command=command)
        # handle() commits before network I/O; failed delivery cannot undo consent.
        await client.send_text(channel_message.provider_chat_id, reply.text, buttons=reply.buttons)
        return None

    @router.message(
        Command(
            "start",
            "help",
            "privacy",
            "profile",
            "edit_profile",
            "retry_profile",
            "delete_me",
            "delete-me",
        )
    )
    async def command_handler(
        message: Message, channel_message: ChannelMessage, command: CommandObject
    ) -> SendMessage | None:
        notice = await respond(channel_message, command.command)
        return (
            SendMessage(chat_id=channel_message.provider_chat_id, text=notice) if notice else None
        )

    @router.message()
    async def fallback_handler(
        message: Message, channel_message: ChannelMessage
    ) -> SendMessage | None:
        notice = await respond(channel_message)
        return (
            SendMessage(chat_id=channel_message.provider_chat_id, text=notice) if notice else None
        )

    @router.callback_query()
    async def consent_handler(
        callback: CallbackQuery, channel_message: ChannelMessage
    ) -> AnswerCallbackQuery | None:
        if webhook:
            notice = await respond(channel_message)
            return AnswerCallbackQuery(callback_query_id=callback.id, text=notice)
        try:
            await respond(channel_message)
        finally:
            await callback.answer()
        return None

    dispatcher.include_router(router)
    return dispatcher
