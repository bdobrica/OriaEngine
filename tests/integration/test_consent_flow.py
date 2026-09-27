from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.types import Update
from sqlalchemy import delete, select

from oria_engine.db.models import Consent, SocialIdentity, User
from oria_engine.db.repositories import UserUnavailableError
from oria_engine.domain.channel import ChannelMessage
from oria_engine.domain.consent import (
    ACCEPTED_TEXT,
    DECLINED_TEXT,
    DISCLAIMER,
    ConsentFlow,
    OnboardingState,
)
from oria_engine.telegram.adapter import create_dispatcher

from .conftest import migrate


@pytest.fixture
async def store(database, infrastructure):
    migrate(infrastructure[0], "upgrade", "head")
    try:
        yield database
    finally:
        async with database.transaction() as session:
            for model in (Consent, SocialIdentity, User):
                await session.execute(delete(model))


def message(text="/start", user="42", callback=None):
    return ChannelMessage("telegram", user, user, "12", "99", datetime.now(UTC), text, callback)


async def decisions(store):
    async with store.transaction() as session:
        return list((await session.scalars(select(Consent).order_by(Consent.revision))).all())


async def test_start_and_preconsent_text_never_record_consent_or_birth_data(store):
    flow = ConsentFlow(store, "2026-09-01")
    for text in (
        "/start",
        "yes",
        "I agree",
        "1990-01-02 12:30 Synthetic City",
        flow.buttons[0].data,
    ):
        reply = await flow.handle(message(text), command="start" if text == "/start" else None)
        assert reply.state == OnboardingState.CONSENT_REQUIRED
        assert DISCLAIMER in reply.text
        assert "2026-09-01" in reply.text
        assert "18+" in reply.buttons[0].text
        assert len(reply.buttons) == 2
    assert await decisions(store) == []
    async with store.transaction() as session:
        users = (await session.scalars(select(User))).all()
        identities = (await session.scalars(select(SocialIdentity))).all()
        assert len(users) == len(identities) == 1
        assert identities[0].user_id == users[0].id
        for model in (User, SocialIdentity, Consent):
            stored_rows = (await session.execute(select(model.__table__))).all()
            assert "1990-01-02" not in repr(stored_rows)
            assert "Synthetic City" not in repr(stored_rows)


async def test_decline_closes_and_start_reoffers_without_changing_decision(store):
    flow = ConsentFlow(store, "v1")
    reply = await flow.handle(message(callback=flow.buttons[1].data))
    assert reply.state == OnboardingState.CLOSED
    assert reply.text == DECLINED_TEXT
    assert not reply.buttons
    (row,) = await decisions(store)
    assert row.status == "declined" and row.declined_at is not None
    assert row.accepted_at is None and row.policy_version == "v1"
    # Fresh instance reads the durable closed state, even after unsolicited birth text.
    restarted = ConsentFlow(store, "v1")
    reply = await restarted.handle(message("synthetic birth data"))
    assert reply.state == OnboardingState.CLOSED
    assert not reply.buttons
    reply = await restarted.handle(message(), command="start")
    assert reply.buttons
    assert (await decisions(store))[0].id == row.id


async def test_accept_advances_persists_and_scopes_to_sender(store):
    flow = ConsentFlow(store, "v1")
    reply = await flow.handle(message(callback=flow.buttons[0].data))
    assert reply.state == OnboardingState.BIRTH_DATE_REQUIRED
    assert reply.text == ACCEPTED_TEXT
    (row,) = await decisions(store)
    assert row.status == "accepted" and row.accepted_at.tzinfo is not None
    assert row.policy_version == "v1" and row.channel == "telegram"
    restarted = ConsentFlow(store, "v1")
    assert (await restarted.handle(message())).state == OnboardingState.BIRTH_DATE_REQUIRED
    assert (await restarted.handle(message(user="43"))).state == OnboardingState.CONSENT_REQUIRED
    await restarted.handle(message(callback=flow.buttons[0].data))
    assert len(await decisions(store)) == 1
    privacy = await restarted.handle(message("/privacy"), command="privacy")
    assert DISCLAIMER in privacy.text and privacy.buttons
    await restarted.handle(message(callback=privacy.buttons[1].data))
    assert (await restarted.handle(message())).state == OnboardingState.CLOSED
    assert [row.status for row in await decisions(store)] == ["accepted", "declined"]


async def test_new_policy_and_stale_or_malformed_buttons_require_current_acceptance(store):
    old = ConsentFlow(store, "v1")
    await old.handle(message(callback=old.buttons[0].data))
    new = ConsentFlow(store, "v2")
    assert (await new.handle(message())).state == OnboardingState.CONSENT_REQUIRED
    for data in (old.buttons[0].data, old.buttons[1].data, "consent:accept", "garbage"):
        reply = await new.handle(message(callback=data))
        assert reply.state == OnboardingState.CONSENT_REQUIRED
        assert reply.buttons == new.buttons
        assert len(await decisions(store)) == 1
    await new.handle(message(callback=new.buttons[0].data))
    assert [row.policy_version for row in await decisions(store)] == ["v1", "v2"]
    reply = await new.handle(message(callback=old.buttons[1].data))
    assert reply.state == OnboardingState.BIRTH_DATE_REQUIRED
    assert [row.status for row in await decisions(store)] == ["accepted", "accepted"]
    longest = ConsentFlow(store, "v" * 64)
    assert all(len(button.data.encode()) <= 64 for button in longest.buttons)


async def test_database_failure_cannot_produce_acceptance(store):
    flow = ConsentFlow(store, "v1")
    await flow.handle(message())
    async with store.transaction() as session:
        user = await session.scalar(select(User))
        user.deleted_at = datetime.now(UTC)
    with pytest.raises(UserUnavailableError):
        await flow.handle(message(callback=flow.buttons[0].data))
    assert await decisions(store) == []


async def test_dispatcher_commits_before_delivery_and_recovers_from_send_failure(store):
    flow = ConsentFlow(store, "v1")
    client = AsyncMock()
    bot = Bot("123456:synthetic-test-token", session=AsyncMock())
    dispatcher = create_dispatcher(client, flow)
    inbound = {
        "message_id": 12,
        "date": 1700000000,
        "chat": {"id": 42, "type": "private"},
        "from": {"id": 42, "is_bot": False, "first_name": "Synthetic"},
        "text": "/start",
    }
    await dispatcher.feed_update(bot, Update.model_validate({"update_id": 1, "message": inbound}))
    assert DISCLAIMER in client.send_text.call_args.args[1]
    accept = client.send_text.call_args.kwargs["buttons"][0].data

    async def fail_send(*args, **kwargs):
        rows = await decisions(store)
        assert len(rows) == 1 and rows[0].status == "accepted"
        raise RuntimeError("synthetic send failure")

    client.send_text.side_effect = fail_send
    callback_message = {**inbound, "from": {"id": bot.id, "is_bot": True, "first_name": "Oria"}}
    await dispatcher.feed_update(
        bot,
        Update.model_validate(
            {
                "update_id": 2,
                "callback_query": {
                    "id": "synthetic-callback",
                    "chat_instance": "synthetic-chat",
                    "from": inbound["from"],
                    "message": callback_message,
                    "data": accept,
                },
            }
        ),
    )
    assert (await decisions(store))[0].status == "accepted"
    # Fresh domain instance can resume after the transport failed.
    reply = await ConsentFlow(store, "v1").handle(message(), command="start")
    assert reply.state == OnboardingState.BIRTH_DATE_REQUIRED
