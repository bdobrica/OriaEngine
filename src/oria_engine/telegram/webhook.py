"""Authenticated, bounded webhook admission; conversation work belongs to workers."""

import asyncio
import hmac
import logging

from aiogram import Bot
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import Update
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import text

from oria_engine.config import ConfigurationError, Settings, validate_telegram_ingress
from oria_engine.privacy.encryption import ProfileEncryption
from oria_engine.queue.broker import Publisher
from oria_engine.queue.events import EventIngress
from oria_engine.telegram.adapter import TelegramChannelClient, create_dispatcher

WEBHOOK_PATH = "/telegram/webhook"
MAX_BODY_BYTES = 256 * 1024
ADMISSION_SECONDS = 5
logger = logging.getLogger(__name__)


class WebhookGateway:
    def __init__(self, bot: Bot, ingress: EventIngress, publisher: Publisher) -> None:
        self.bot = bot
        self.ingress = ingress
        self.publisher = publisher
        self.dispatcher = create_dispatcher(
            TelegramChannelClient(bot), ingress=ingress, publisher=publisher, webhook=True
        )

    async def database_ready(self) -> bool:
        async with self.ingress.database.transaction() as session:
            return bool(await session.scalar(text("SELECT 1")) == 1)

    async def redis_ready(self) -> bool:
        return bool(await asyncio.to_thread(self.publisher.client.ping))

    async def receive(self, request: Request, secret: str) -> JSONResponse:
        supplied = request.headers.getlist("x-telegram-bot-api-secret-token")
        if len(supplied) != 1 or not hmac.compare_digest(
            supplied[0].encode("utf-8"), secret.encode("ascii")
        ):
            raise HTTPException(403, "Forbidden")
        try:
            async with asyncio.timeout(ADMISSION_SECONDS):
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BODY_BYTES:
                        raise HTTPException(413, "Request too large")
                    body.extend(chunk)
                try:
                    update = Update.model_validate_json(bytes(body), context={"bot": self.bot})
                except (ValidationError, ValueError):
                    # Never return Pydantic diagnostics, input values or Telegram metadata.
                    raise HTTPException(400, "Invalid update") from None
                result = await self.dispatcher.feed_update(self.bot, update)
                if isinstance(result, AnswerCallbackQuery):
                    return JSONResponse(
                        {
                            "method": "answerCallbackQuery",
                            "callback_query_id": result.callback_query_id,
                        }
                    )
                return JSONResponse({"ok": True})
        except HTTPException:
            raise
        except Exception:
            logger.error("update_failed")
            # A commit may already exist. Provider retries and worker scans safely reuse it.
            raise HTTPException(
                503, "Temporarily unavailable", headers={"Retry-After": "1"}
            ) from None


def validate_webhook_settings(settings: Settings) -> ProfileEncryption:
    validate_telegram_ingress(settings)
    if not settings.telegram_webhook_secret.get_secret_value():
        raise ConfigurationError("Webhook ingress requires TELEGRAM_WEBHOOK_SECRET")
    return ProfileEncryption(settings)


def webhook_url(settings: Settings) -> str:
    if not settings.telegram_webhook_base_url:
        raise ConfigurationError("Webhook registration requires TELEGRAM_WEBHOOK_BASE_URL")
    return settings.telegram_webhook_base_url.rstrip("/") + WEBHOOK_PATH
