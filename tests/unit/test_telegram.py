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
from oria_engine.domain.channel import ChannelButton
from oria_engine.domain.consent import ConsentReply, OnboardingState
from oria_engine.observability import configure_logging, correlation_id, update_id
from oria_engine.telegram.__main__ import main, run_polling
from oria_engine.telegram.adapter import (
    TelegramChannelClient,
    create_dispatcher,
    normalize_callback,
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
    flow = AsyncMock()
    await create_dispatcher(client, flow).feed_update(bot, update(chat_type=kind))
    flow.handle.assert_not_called()
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
    flow = AsyncMock()
    await create_dispatcher(client, flow).feed_update(Bot(TOKEN), event)
    flow.handle.assert_not_called()
    assert normalize_update(event) is None
    client.send_text.assert_not_called()


@pytest.mark.parametrize(
    ("text", "command"),
    [
        ("/start", "start"),
        ("/start deep-link", "start"),
        ("/help", "help"),
        ("/privacy", "privacy"),
        ("/delete-me", "delete-me"),
        ("/delete_me", "delete_me"),
        ("private birth details", None),
        ("/unknown", None),
    ],
)
async def test_private_replies_use_channel_client(text, command):
    client = AsyncMock()
    flow = AsyncMock()
    flow.handle.return_value = ConsentReply(OnboardingState.CONSENT_REQUIRED, "disclosure")
    await create_dispatcher(client, flow).feed_update(Bot(TOKEN), update(text))
    assert flow.handle.call_args.kwargs == {"command": command}
    assert flow.handle.call_args.args[0].text == text
    client.send_text.assert_awaited_once_with("42", "disclosure", buttons=())
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


@pytest.mark.parametrize("fails", [False, "send", "database"])
async def test_logs_exclude_payload_and_errors(fails, capsys):
    configure_logging(Settings(telegram_bot_token=SecretStr(TOKEN)))
    client = AsyncMock()

    async def send(*args, **kwargs):
        assert correlation_id.get() is not None
        assert update_id.get() == 99
        if fails == "send":
            raise RuntimeError("private birth details " + TOKEN)

    client.send_text.side_effect = send
    flow = AsyncMock()
    flow.handle.return_value = ConsentReply(OnboardingState.CONSENT_REQUIRED, "disclosure")
    if fails == "database":
        flow.handle.side_effect = RuntimeError("private birth details " + TOKEN)
    await create_dispatcher(client, flow).feed_update(Bot(TOKEN), update("private birth details"))
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


@pytest.mark.parametrize("old_policy", ["2026-09-01", "2026-09-28"])
async def test_polling_requires_encryption_and_updated_disclosure(encryption, old_policy):
    with patch("oria_engine.telegram.__main__.Bot") as bot:
        with pytest.raises(ConfigurationError, match="encryption"):
            await run_polling(Settings(telegram_bot_token=SecretStr(TOKEN)))
        with (
            patch("oria_engine.telegram.__main__.ProfileEncryption", return_value=encryption),
            pytest.raises(ConfigurationError, match="ORIA_POLICY_VERSION"),
        ):
            await run_polling(
                Settings(telegram_bot_token=SecretStr(TOKEN), oria_policy_version=old_policy)
            )
        bot.assert_not_called()


@pytest.mark.parametrize("outcome", ["success", "error", "cancel", "webhook"])
async def test_polling_lifecycle(outcome, encryption):
    bot = AsyncMock()
    bot.get_webhook_info.return_value = WebhookInfo(
        url="https://example.test/hook" if outcome == "webhook" else "",
        has_custom_certificate=False,
        pending_update_count=0,
    )
    dispatcher = AsyncMock()
    database = AsyncMock()
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
        patch("oria_engine.telegram.__main__.Database", return_value=database),
        patch("oria_engine.telegram.__main__.ProfileEncryption", return_value=encryption),
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
        database.close.assert_not_called()
    else:
        database.close.assert_awaited_once()
        dispatcher.start_polling.assert_awaited_once_with(
            bot,
            allowed_updates=["message", "callback_query"],
            handle_as_tasks=False,
            close_bot_session=False,
        )


def callback_update(data="consent:accept:synthetic", **changes):
    message = update().message.model_dump()
    message["from_user"] = {"id": 123456, "is_bot": True, "first_name": "Oria"}
    callback = {
        "id": "synthetic-callback",
        "chat_instance": "synthetic-chat",
        "from": {"id": 42, "is_bot": False, "first_name": "Synthetic"},
        "message": message,
        "data": data,
    }
    callback.update(changes)
    return Update.model_validate({"update_id": 100, "callback_query": callback})


async def test_callback_uses_clicker_identity_and_acknowledges_even_send_failure():
    event = callback_update()
    normalized = normalize_callback(event, 123456)
    assert normalized.provider_user_id == normalized.provider_chat_id == "42"
    assert normalized.text == ""
    assert normalized.callback_data == "consent:accept:synthetic"
    assert "consent:accept" not in repr(normalized)
    flow = AsyncMock()
    flow.handle.return_value = ConsentReply(OnboardingState.BIRTH_DATE_REQUIRED, "accepted")
    client = AsyncMock()
    client.send_text.side_effect = RuntimeError("sensitive")
    session = AsyncMock()
    await create_dispatcher(client, flow).feed_update(Bot(TOKEN, session=session), event)
    assert flow.handle.call_args.args[0].provider_user_id == "42"
    assert session.call_args.args[1].callback_query_id == "synthetic-callback"


@pytest.mark.parametrize(
    "changes",
    [
        {"message": None, "inline_message_id": "inline"},
        {"from": {"id": 43, "is_bot": False, "first_name": "Other"}},
        {"from": {"id": 42, "is_bot": True, "first_name": "Bot"}},
        {"data": None},
        {"message": update(chat_type="group").message.model_dump()},
        {"message": update().message.model_dump()},
        {"message": {"message_id": 12, "date": 0, "chat": {"id": 42, "type": "private"}}},
    ],
)
async def test_unsupported_callbacks_do_not_reach_consent(changes):
    flow = AsyncMock()
    await create_dispatcher(AsyncMock(), flow).feed_update(Bot(TOKEN), callback_update(**changes))
    flow.handle.assert_not_called()


async def test_outbound_consent_keyboard():
    session = AsyncMock()
    await TelegramChannelClient(Bot(TOKEN, session=session)).send_text(
        "42", "policy", buttons=(ChannelButton("Agree", "consent:accept:test"),)
    )
    method = session.call_args.args[1]
    assert method.parse_mode is None
    button = method.reply_markup.inline_keyboard[0][0]
    assert button.text == "Agree"
    assert button.callback_data == "consent:accept:test"


def test_entrypoint_suppresses_sensitive_startup_exception(capsys):
    with (
        patch("oria_engine.telegram.__main__.run_polling", side_effect=RuntimeError(TOKEN)),
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 1
    assert TOKEN not in capsys.readouterr().err


async def test_queue_ingress_does_not_run_flow_and_enqueue_failure_is_recoverable():
    from unittest.mock import Mock
    from uuid import uuid4

    ingress = AsyncMock()
    identifier = uuid4()
    ingress.accept.return_value = identifier
    publisher = Mock()
    publisher.send.side_effect = RuntimeError("Redis unavailable")
    flow = AsyncMock()
    client = AsyncMock()
    await create_dispatcher(client, flow, ingress=ingress, publisher=publisher).feed_update(
        Bot(TOKEN), update("/profile")
    )
    ingress.accept.assert_awaited_once()
    assert ingress.accept.call_args.kwargs == {"command": "profile"}
    publisher.send.assert_called_once_with(str(identifier))
    flow.handle.assert_not_called()
    client.send_text.assert_not_called()


async def test_queue_ingress_retries_durability_before_callback_ack():
    from uuid import uuid4

    ingress = AsyncMock()
    ingress.accept.side_effect = [RuntimeError("database down"), uuid4()]
    session = AsyncMock()
    await create_dispatcher(AsyncMock(), ingress=ingress).feed_update(
        Bot(TOKEN, session=session), callback_update()
    )
    assert ingress.accept.await_count == 2
    assert session.call_args.args[1].callback_query_id == "synthetic-callback"


async def test_unavailable_user_does_not_block_polling_with_endless_retries():
    from oria_engine.db.repositories import UserUnavailableError

    ingress = AsyncMock()
    ingress.accept.side_effect = UserUnavailableError("User unavailable")
    client = AsyncMock()
    await asyncio.wait_for(
        create_dispatcher(client, ingress=ingress).feed_update(Bot(TOKEN), update()), 1
    )
    ingress.accept.assert_awaited_once()
    client.send_text.assert_not_called()
