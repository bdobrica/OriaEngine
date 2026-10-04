"""Published ingress v1 response/authentication behavior in production configuration."""

import base64
import secrets
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from aiogram import Bot

from oria_engine.app import create_app
from oria_engine.config import Settings
from oria_engine.queue.broker import Publisher
from oria_engine.queue.events import EventIngress
from oria_engine.queue.limits import LIMIT_REPLY, AdmissionRejected
from oria_engine.telegram.webhook import WEBHOOK_PATH, WebhookGateway


@pytest.fixture
async def client():
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+psycopg://oria:synthetic@localhost:5432/oria",
        redis_url="redis://localhost:6379/0",
        second_context_base_url="http://localhost:8080",
        astrology_mcp_url="http://localhost:8000/mcp",
        telegram_bot_token="123456:synthetic-webhook-token",
        telegram_webhook_base_url="https://example.invalid",
        telegram_webhook_secret=secrets.token_urlsafe(32),
        profile_encryption_key=base64.b64encode(secrets.token_bytes(32)).decode(),
        oria_policy_version="2026-10-03.2",
    )
    bot = Bot(settings.telegram_bot_token.get_secret_value())
    ingress = AsyncMock(spec=EventIngress)
    ingress.accept.return_value = uuid4()
    gateway = WebhookGateway(bot, ingress, Mock(spec=Publisher))
    app = create_app(settings, webhook_gateway=gateway)
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            client.headers["X-Telegram-Bot-Api-Secret-Token"] = (
                settings.telegram_webhook_secret.get_secret_value()
            )
            yield client, ingress
    finally:
        await bot.session.close()


async def test_additive_telegram_fields_remain_compatible_and_private(client):
    client, ingress = client
    response = await client.post(
        WEBHOOK_PATH,
        json={
            "update_id": 11,
            "future_field": {"untrusted": "value"},
            "message": {
                "message_id": 1,
                "date": 1700000000,
                "chat": {"id": 42, "type": "private", "future_chat_field": "value"},
                "from": {"id": 42, "is_bot": False, "first_name": "Synthetic"},
                "text": "/start",
                "future_message_field": "value",
            },
        },
    )
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert "future" not in repr(ingress.accept.call_args.args[0])
    ingress.accept.assert_awaited_once()


async def test_authentication_and_validation_errors_have_fixed_response_shapes(client):
    client, ingress = client
    invalid = await client.post(WEBHOOK_PATH, content=b"not json")
    assert invalid.status_code == 400 and invalid.json() == {"detail": "Invalid update"}
    client.headers.pop("X-Telegram-Bot-Api-Secret-Token")
    unauthenticated = await client.post(WEBHOOK_PATH, content=b"not json")
    assert unauthenticated.status_code == 403
    assert unauthenticated.json() == {"detail": "Forbidden"}
    ingress.accept.assert_not_called()


async def test_unknown_update_is_ignored_and_production_docs_are_disabled(client):
    client, ingress = client
    response = await client.post(WEBHOOK_PATH, json={"update_id": 12, "future_update": {}})
    assert response.status_code == 200 and response.json() == {"ok": True}
    ingress.accept.assert_not_called()
    assert (await client.get("/docs")).status_code == 404
    assert (await client.get("/openapi.json")).status_code == 404
    assert (await client.get(WEBHOOK_PATH)).status_code == 405


async def test_admission_limits_are_permanent_200_with_optional_telegram_notice(client):
    client, ingress = client
    event = {
        "update_id": 11,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Synthetic"},
            "text": "Hi",
        },
    }
    ingress.accept.side_effect = AdmissionRejected(LIMIT_REPLY)
    response = await client.post(WEBHOOK_PATH, json=event)
    assert response.status_code == 200
    assert response.json() == {"method": "sendMessage", "chat_id": "42", "text": LIMIT_REPLY}
    ingress.accept.side_effect = AdmissionRejected()
    assert (await client.post(WEBHOOK_PATH, json=event)).json() == {"ok": True}
