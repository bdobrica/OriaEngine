import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.methods import SendMessage
from aiogram.types import Update, WebhookInfo
from pydantic import SecretStr

from oria_engine.config import ConfigurationError, Settings
from oria_engine.domain.channel import HELP_TEXT, START_TEXT
from oria_engine.observability import configure_logging, correlation_id, update_id
from oria_engine.telegram.__main__ import main, run_polling
from oria_engine.telegram.adapter import (
    TelegramChannelClient,
    create_dispatcher,
    normalize_update,
)

TOKEN = "123456:synthetic-test-token"


def update(text="/start", chat_type="private", **changes):
    message = {
        "message_id": 12,
        "date": 1700000000,
        "chat": {"id": 42, "type": chat_type},
        "from": {"id": 42, "is_bot": False, "first_name": "Synthetic", "username": "fixture"},
        "text": text,
    }
    message.update(changes)
    return Update.model_validate({"update_id": 99, "message": message})


def test_normalization_minimizes_metadata():
    before = datetime.now(UTC)
    message = normalize_update(update("sensitive birth details"))
    assert message.provider == "telegram"
    assert message.provider_user_id == message.provider_chat_id == "42"
    assert message.provider_message_id == "12"
    assert message.provider_update_id == "99"
    assert before <= message.received_at <= datetime.now(UTC)
    assert message.text == "sensitive birth details"
    assert "sensitive" not in repr(message)
    assert not hasattr(message, "username")
    assert not hasattr(message, "first_name")


@pytest.mark.parametrize("kind", ["group", "supergroup", "channel"])
async def test_nonprivate_chats_are_ignored(kind):
    client = AsyncMock()
    bot = Bot(TOKEN)
    await create_dispatcher(client).feed_update(bot, update(chat_type=kind))
    client.send_text.assert_not_called()


@pytest.mark.parametrize(
    "event",
    [
        update(text=None),
        update(**{"from": None}),
        update(**{"from": {"id": 42, "is_bot": True, "first_name": "Bot"}}),
        update(business_connection_id="business"),
        Update(update_id=99),
        Update(update_id=99, edited_message=update().message),
        Update(update_id=99, channel_post=update(chat_type="channel").message),
    ],
)
async def test_unsupported_updates_are_ignored(event):
    client = AsyncMock()
    await create_dispatcher(client).feed_update(Bot(TOKEN), event)
    assert normalize_update(event) is None
    client.send_text.assert_not_called()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/start", START_TEXT),
        ("/start deep-link", START_TEXT),
        ("/help", HELP_TEXT),
        ("private birth details", HELP_TEXT),
        ("/unknown", HELP_TEXT),
    ],
)
async def test_private_replies_use_channel_client(text, expected):
    client = AsyncMock()
    await create_dispatcher(client).feed_update(Bot(TOKEN), update(text))
    client.send_text.assert_awaited_once_with("42", expected)
    assert correlation_id.get() is None
    assert update_id.get() is None


async def test_outbound_api_is_plain_text():
    session = AsyncMock()
    bot = Bot(TOKEN, session=session, default=DefaultBotProperties(parse_mode="HTML"))
    await TelegramChannelClient(bot).send_text("42", "<plain> & text")
    method = session.call_args.args[1]
    assert isinstance(method, SendMessage)
    assert method.chat_id == 42
    assert method.text == "<plain> & text"
    assert method.parse_mode is None


@pytest.mark.parametrize("fails", [False, True])
async def test_logs_exclude_payload_and_errors(fails, capsys):
    configure_logging(Settings(telegram_bot_token=SecretStr(TOKEN)))
    client = AsyncMock()

    async def send(*args):
        assert correlation_id.get() is not None
        assert update_id.get() == 99
        if fails:
            raise RuntimeError("private birth details " + TOKEN)

    client.send_text.side_effect = send
    await create_dispatcher(client).feed_update(Bot(TOKEN), update("private birth details"))
    logs = capsys.readouterr().err
    assert TOKEN not in logs
    assert "private birth details" not in logs
    events = [json.loads(line) for line in logs.splitlines()]
    record = next(
        e for e in events if e["event"] == ("update_failed" if fails else "update_completed")
    )
    assert record["update_id"] == 99
    assert record["correlation_id"]
    assert correlation_id.get() is None


@pytest.mark.parametrize("production", [False, True])
async def test_polling_configuration_fails_before_network(production):
    settings = Settings()
    if production:
        settings = settings.model_copy(update={"app_env": "production"})
    with patch("oria_engine.telegram.__main__.Bot") as bot:
        with pytest.raises(ConfigurationError):
            await run_polling(settings)
        bot.assert_not_called()


@pytest.mark.parametrize("outcome", ["success", "error", "cancel", "webhook"])
async def test_polling_lifecycle(outcome):
    bot = AsyncMock()
    bot.get_webhook_info.return_value = WebhookInfo(
        url="https://example.test/hook" if outcome == "webhook" else "",
        has_custom_certificate=False,
        pending_update_count=0,
    )
    dispatcher = AsyncMock()
    failure = {
        "error": RuntimeError,
        "cancel": asyncio.CancelledError,
        "webhook": ConfigurationError,
    }.get(outcome)
    if outcome in {"error", "cancel"}:
        dispatcher.start_polling.side_effect = failure
    with (
        patch("oria_engine.telegram.__main__.Bot", return_value=bot),
        patch("oria_engine.telegram.__main__.create_dispatcher", return_value=dispatcher),
    ):
        if failure:
            with pytest.raises(failure):
                await run_polling(Settings(telegram_bot_token=SecretStr(TOKEN)))
        else:
            await run_polling(Settings(telegram_bot_token=SecretStr(TOKEN)))
    bot.session.close.assert_awaited_once()
    bot.delete_webhook.assert_not_called()
    if outcome == "webhook":
        dispatcher.start_polling.assert_not_called()
    else:
        dispatcher.start_polling.assert_awaited_once_with(
            bot, allowed_updates=["message"], handle_as_tasks=False, close_bot_session=False
        )


def test_entrypoint_suppresses_sensitive_startup_exception(capsys):
    with (
        patch("oria_engine.telegram.__main__.run_polling", side_effect=RuntimeError(TOKEN)),
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 1
    assert TOKEN not in capsys.readouterr().err
