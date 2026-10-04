import asyncio
import base64
import secrets
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

import httpx
import pytest
from aiogram import Bot
from aiogram.types import User
from fastapi.testclient import TestClient

from oria_engine.app import create_app
from oria_engine.config import ConfigurationError, Settings
from oria_engine.db.repositories import UserUnavailableError
from oria_engine.observability import correlation_id, update_id
from oria_engine.telegram.webhook import MAX_BODY_BYTES, WEBHOOK_PATH, WebhookGateway
from oria_engine.telegram.webhook_admin import configure_webhook, main

TOKEN = "123456:synthetic-webhook-token"


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        telegram_bot_token=TOKEN,
        telegram_webhook_secret=secrets.token_urlsafe(32),
        telegram_webhook_base_url="https://example.invalid/oria/",
        profile_encryption_key=base64.b64encode(secrets.token_bytes(32)).decode(),
    )


@pytest.fixture
async def gateway(settings):
    bot = Bot(TOKEN)
    ingress = AsyncMock()
    ingress.accept.return_value = uuid4()
    publisher = Mock()
    gateway = WebhookGateway(bot, ingress, publisher)
    gateway.database_ready = AsyncMock(return_value=True)
    gateway.redis_ready = AsyncMock(return_value=True)
    try:
        yield gateway
    finally:
        await bot.session.close()


@pytest.fixture
async def client(settings, gateway):
    app = create_app(settings, webhook_gateway=gateway)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        client.headers["X-Telegram-Bot-Api-Secret-Token"] = (
            settings.telegram_webhook_secret.get_secret_value()
        )
        yield client


def payload(text="/start", **changes):
    message = {
        "message_id": 12,
        "date": 1700000000,
        "chat": {"id": 42, "type": "private"},
        "from": {"id": 42, "is_bot": False, "first_name": "Synthetic"},
        "text": text,
    }
    message.update(changes)
    return {"update_id": 99, "message": message}


def callback():
    event = payload()
    event["message"]["from"] = {"id": 123456, "is_bot": True, "first_name": "Bot"}
    return {
        "update_id": 100,
        "callback_query": {
            "id": "synthetic-callback",
            "chat_instance": "synthetic",
            "from": {"id": 42, "is_bot": False, "first_name": "Synthetic"},
            "message": event["message"],
            "data": "consent:accept:synthetic",
        },
    }


@pytest.mark.parametrize(
    "text,command",
    [
        ("/start", "start"),
        ("/help argument", "help"),
        ("/profile", "profile"),
        ("/edit_profile", "edit_profile"),
        ("/privacy", "privacy"),
        ("/delete-me", "delete-me"),
        ("/delete_me", "delete_me"),
        ("/retry_profile", "retry_profile"),
        ("/unknown", None),
        ("synthetic text", None),
    ],
)
async def test_admission_enqueues_only_committed_uuid(client, gateway, text, command):
    def enqueue(identifier):
        gateway.ingress.accept.assert_awaited_once()
        assert identifier == str(gateway.ingress.accept.return_value)

    gateway.publisher.send.side_effect = enqueue
    response = await client.post(WEBHOOK_PATH, json=payload(text))
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert UUID(response.headers["x-request-id"]).version == 4
    gateway.ingress.accept.assert_awaited_once()
    assert gateway.ingress.accept.call_args.kwargs == {"command": command}
    assert gateway.ingress.accept.call_args.args[0].provider_user_id == "42"
    gateway.publisher.send.assert_called_once()
    assert correlation_id.get() is update_id.get() is None


@pytest.mark.parametrize("secret", [None, "wrong", "", "☃"])
async def test_secret_checked_before_body_parsing(client, gateway, secret):
    client.headers.pop("X-Telegram-Bot-Api-Secret-Token")
    headers = {} if secret is None else {"X-Telegram-Bot-Api-Secret-Token": secret.encode()}
    response = await client.post(WEBHOOK_PATH, content=b"invalid json", headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}
    gateway.ingress.accept.assert_not_called()
    gateway.publisher.send.assert_not_called()


async def test_duplicate_secret_headers_rejected(client, gateway, settings):
    client.headers.pop("X-Telegram-Bot-Api-Secret-Token")
    secret = settings.telegram_webhook_secret.get_secret_value()
    response = await client.post(
        WEBHOOK_PATH,
        json=payload(),
        headers=[
            ("X-Telegram-Bot-Api-Secret-Token", secret),
            ("X-Telegram-Bot-Api-Secret-Token", secret),
        ],
    )
    assert response.status_code == 403
    gateway.ingress.accept.assert_not_called()


@pytest.mark.parametrize("body", [b"not json", b"[]", b"{}", b'{"update_id":"private"}'])
async def test_malformed_body_returns_generic_error(client, gateway, body):
    response = await client.post(WEBHOOK_PATH, content=body)
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid update"}
    gateway.ingress.accept.assert_not_called()


@pytest.mark.parametrize("chunked", [False, True])
async def test_body_limit_applies_without_content_length(client, gateway, chunked):
    async def chunks():
        for _ in range(5):
            yield b"x" * (MAX_BODY_BYTES // 4)

    response = await client.post(
        WEBHOOK_PATH, content=chunks() if chunked else b"x" * (MAX_BODY_BYTES + 1)
    )
    assert response.status_code == 413
    gateway.ingress.accept.assert_not_called()


@pytest.mark.parametrize(
    "event",
    [
        {"update_id": 1, "future_update_type": {"private": "value"}},
        {"update_id": 1, "edited_message": payload()["message"]},
        payload(chat={"id": -1, "type": "group"}),
        payload(text=None),
        payload(business_connection_id="synthetic"),
        payload(**{"from": {"id": 42, "is_bot": True, "first_name": "Bot"}}),
    ],
)
async def test_unsupported_updates_are_acknowledged_without_storage(client, gateway, event):
    response = await client.post(WEBHOOK_PATH, json=event)
    assert response.status_code == 200
    gateway.ingress.accept.assert_not_called()
    gateway.publisher.send.assert_not_called()


async def test_callback_acknowledgement_uses_webhook_response(client, gateway):
    with patch.object(gateway.bot, "answer_callback_query", new_callable=AsyncMock) as answer:
        response = await client.post(WEBHOOK_PATH, json=callback())
        assert response.status_code == 200
        assert response.json() == {
            "method": "answerCallbackQuery",
            "callback_query_id": "synthetic-callback",
        }
        assert gateway.ingress.accept.call_args.args[0].provider_user_id == "42"
        answer.assert_not_called()


async def test_foreign_callback_is_ignored(client, gateway):
    event = callback()
    event["callback_query"]["from"]["id"] = 43
    assert (await client.post(WEBHOOK_PATH, json=event)).status_code == 200
    gateway.ingress.accept.assert_not_called()


@pytest.mark.parametrize("failure", ["database", "queue", "timeout"])
async def test_failure_is_bounded_retryable_and_payload_free(
    client, gateway, monkeypatch, capsys, failure
):
    if failure == "database":
        gateway.ingress.accept.side_effect = RuntimeError("private error body")
    elif failure == "queue":
        gateway.publisher.send.side_effect = RuntimeError("private error body")
    else:
        monkeypatch.setattr("oria_engine.telegram.webhook.ADMISSION_SECONDS", 0.01)

        async def blocked(*args, **kwargs):
            await asyncio.sleep(10)

        gateway.ingress.accept.side_effect = blocked
    response = await client.post(WEBHOOK_PATH, json=payload("private message body"))
    assert response.status_code == 503
    assert response.json() == {"detail": "Temporarily unavailable"}
    assert response.headers["retry-after"] == "1"
    gateway.ingress.accept.assert_awaited_once()
    if failure != "queue":
        gateway.publisher.send.assert_not_called()
    assert "private" not in capsys.readouterr().err


async def test_request_cancellation_propagates_without_publication(client, gateway):
    entered = asyncio.Event()

    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.sleep(10)

    gateway.ingress.accept.side_effect = blocked
    task = asyncio.create_task(client.post(WEBHOOK_PATH, json=payload()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    gateway.publisher.send.assert_not_called()


async def test_webhook_logs_exclude_secret_text_metadata_and_callback_ids(client, settings, capsys):
    text = "synthetic-private-message"
    event = payload(text, **{"from": {"id": 42, "is_bot": False, "first_name": "private-name"}})
    assert (await client.post(WEBHOOK_PATH, json=event)).status_code == 200
    assert (await client.post(WEBHOOK_PATH, json=callback())).status_code == 200
    output = capsys.readouterr().err
    for value in (
        text,
        "private-name",
        "synthetic-callback",
        TOKEN,
        settings.telegram_webhook_secret.get_secret_value(),
    ):
        assert value not in output


async def test_deleting_user_is_acknowledged_without_queue_work(client, gateway):
    gateway.ingress.accept.side_effect = UserUnavailableError()
    assert (await client.post(WEBHOOK_PATH, json=payload())).status_code == 200
    gateway.publisher.send.assert_not_called()


async def test_command_mentions_keep_polling_semantics(client, gateway):
    with patch.object(gateway.bot, "me", new_callable=AsyncMock) as me:
        me.return_value = User(id=123456, is_bot=True, first_name="Bot", username="oria_test")
        await client.post(WEBHOOK_PATH, json=payload("/start@oria_test"))
        assert gateway.ingress.accept.call_args.kwargs == {"command": "start"}
        await client.post(WEBHOOK_PATH, json=payload("/start@other_bot"))
        assert gateway.ingress.accept.call_args.kwargs == {"command": None}


async def test_gateway_readiness_tracks_dependencies(client, gateway):
    assert (await client.get("/readyz")).json() == {
        "status": "ready",
        "checks": {"database": True, "redis": True},
    }
    gateway.redis_ready.return_value = False
    assert (await client.get("/readyz")).status_code == 503
    assert (await client.get("/healthz")).status_code == 200


def test_gateway_disabled_and_incomplete_settings_fail_safely(settings):
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.post(WEBHOOK_PATH, json=payload()).status_code == 404
    for field in ("telegram_bot_token", "profile_encryption_key"):
        with pytest.raises(ConfigurationError):
            create_app(settings.model_copy(update={field: Settings.model_fields[field].default}))
    with pytest.raises(ConfigurationError, match="ORIA_POLICY_VERSION"):
        create_app(settings.model_copy(update={"oria_policy_version": "2026-10-03.1"}))


async def test_gateway_requires_active_lifespan(settings, gateway):
    app = create_app(settings, webhook_gateway=gateway)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.post(WEBHOOK_PATH, json=payload())).status_code == 503
    gateway.ingress.accept.assert_not_called()


def test_runtime_resources_closed_without_implicit_registration(settings):
    with (
        patch("oria_engine.app.Database") as database,
        patch("oria_engine.app.Publisher") as publisher,
        patch("oria_engine.app.Bot") as bot,
    ):
        database.return_value.close = AsyncMock()
        bot.return_value.session.close = AsyncMock()
        with TestClient(create_app(settings)) as client:
            assert client.get("/healthz").status_code == 200
            bot.return_value.set_webhook.assert_not_called()
            bot.return_value.get_webhook_info.assert_not_called()
        database.return_value.close.assert_awaited_once()
        bot.return_value.session.close.assert_awaited_once()
        publisher.return_value.close.assert_called_once()


def test_startup_failure_disposes_prior_resources(settings):
    with (
        patch("oria_engine.app.Database") as database,
        patch("oria_engine.app.Publisher", side_effect=RuntimeError("unavailable")),
    ):
        database.return_value.close = AsyncMock()
        with pytest.raises(RuntimeError), TestClient(create_app(settings)):
            pass
        database.return_value.close.assert_awaited_once()


@pytest.mark.parametrize("action", ["set", "reset", "delete"])
@pytest.mark.parametrize("drop", [False, True])
async def test_management_preserves_pending_updates_unless_explicit(settings, action, drop):
    with patch("oria_engine.telegram.webhook_admin.Bot") as factory:
        bot = factory.return_value
        bot.session.close = AsyncMock()
        bot.set_webhook = AsyncMock(return_value=True)
        bot.delete_webhook = AsyncMock(return_value=True)
        await configure_webhook(settings, action, drop_pending_updates=drop)
        if action == "delete":
            bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=drop)
            bot.set_webhook.assert_not_called()
        else:
            bot.set_webhook.assert_awaited_once_with(
                url="https://example.invalid/oria/telegram/webhook",
                secret_token=settings.telegram_webhook_secret.get_secret_value(),
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=drop,
            )
        bot.session.close.assert_awaited_once()


@pytest.mark.parametrize("failure", ["exception", "false", "cancelled"])
async def test_management_failure_still_closes_bot(settings, failure):
    with patch("oria_engine.telegram.webhook_admin.Bot") as factory:
        bot = factory.return_value
        bot.session.close = AsyncMock()
        bot.set_webhook = AsyncMock(return_value=False)
        error = ConfigurationError
        if failure != "false":
            error = asyncio.CancelledError if failure == "cancelled" else RuntimeError
            bot.set_webhook.side_effect = error("private details")
        with pytest.raises(error):
            await configure_webhook(settings, "set")
        bot.session.close.assert_awaited_once()


def test_management_cli_does_not_print_provider_details(settings, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["webhook_admin", "set"])
    with (
        patch("oria_engine.telegram.webhook_admin.load_settings", return_value=settings),
        patch(
            "oria_engine.telegram.webhook_admin.configure_webhook", new_callable=AsyncMock
        ) as configure,
    ):
        configure.side_effect = RuntimeError("private token and payload")
        with pytest.raises(SystemExit) as error:
            main()
    assert error.value.code == 1
    assert "private" not in capsys.readouterr().err
