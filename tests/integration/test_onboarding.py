import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.types import Update
from sqlalchemy import delete, select

from oria_engine.config import Settings
from oria_engine.db.birth_profiles import BirthProfileRepository, ConsentRequiredError
from oria_engine.db.models import BirthProfile, Consent, OnboardingProgress, SocialIdentity, User
from oria_engine.db.onboarding import OnboardingRepository
from oria_engine.db.repositories import ConsentRepository
from oria_engine.domain.channel import ChannelMessage
from oria_engine.domain.consent import ConsentFlow
from oria_engine.domain.consent import OnboardingState as State
from oria_engine.domain.onboarding import OnboardingFlow
from oria_engine.domain.places import UnavailablePlaceResolver
from oria_engine.observability import configure_logging
from oria_engine.telegram.adapter import create_dispatcher

from .conftest import migrate


@pytest.fixture
async def store(database, infrastructure):
    migrate(infrastructure[0], "upgrade", "head")
    try:
        yield database
    finally:
        async with database.transaction() as session:
            for model in (OnboardingProgress, BirthProfile, Consent, SocialIdentity, User):
                await session.execute(delete(model))


def message(text="", callback=None, user="42"):
    return ChannelMessage("telegram", user, user, "12", "99", datetime.now(UTC), text, callback)


def flow(store, encryption, birth_payload, policy="v1"):
    resolver = AsyncMock()
    resolver.resolve.return_value = (birth_payload.birth_place,)
    return ConsentFlow(store, policy, OnboardingFlow(encryption, policy, resolver))


def button(reply, label):
    return next(b.data for b in reply.buttons if b.text == label)


async def setup_to_time(f):
    await f.handle(message(callback=f.buttons[0].data))
    return await f.handle(message("1990-04-13"))


async def owner(store):
    async with store.transaction() as session:
        return await session.scalar(
            select(User.id).join(SocialIdentity).where(SocialIdentity.provider_user_id == "42")
        )


@pytest.mark.parametrize(
    ("time_input", "accuracy"),
    [
        ("03:42", "exact"),
        ("approximate 03:42", "approximate"),
        ("unknown", "unknown"),
    ],
)
async def test_full_flow_survives_restart_and_requires_confirmation(
    store, encryption, birth_payload, time_input, accuracy
):
    f = flow(store, encryption, birth_payload)
    assert (await setup_to_time(f)).state == State.BIRTH_TIME_REQUIRED
    f = flow(store, encryption, birth_payload)
    assert (await f.handle(message("/start"), command="start")).state == State.BIRTH_TIME_REQUIRED
    assert (await f.handle(message(time_input))).state == State.BIRTH_PLACE_REQUIRED
    reply = await f.handle(message("Cluj-Napoca, Romania"))
    assert reply.state == State.BIRTH_PLACE_CONFIRMATION
    # Fresh instance reloads normalized candidates and callback token from encrypted storage.
    f = flow(store, encryption, birth_payload)
    reply = await f.handle(message(callback=reply.buttons[0].data))
    assert reply.state == State.PROFILE_CONFIRMATION
    assert "1990-04-13" in reply.text and accuracy in reply.text
    confirm = button(reply, "Confirm profile")
    user_id = await owner(store)
    async with store.transaction() as session:
        assert await session.scalar(select(BirthProfile)) is None
        row = await session.scalar(select(OnboardingProgress))
        assert b"1990-04-13" not in row.encrypted_payload
        assert b"Cluj" not in row.encrypted_payload
    # Free text cannot confirm, and another sender cannot use these buttons.
    assert (await f.handle(message("yes"))).state == State.PROFILE_CONFIRMATION
    await f.handle(message(callback=f.buttons[0].data, user="43"))
    assert (await f.handle(message(callback=confirm, user="43"))).state == State.BIRTH_DATE_REQUIRED
    assert (await f.handle(message(callback=confirm))).state == State.COMPUTING_PROFILE
    assert (await f.handle(message(callback=confirm))).state == State.COMPUTING_PROFILE
    async with store.transaction() as session:
        saved = await BirthProfileRepository(session, encryption, policy_version="v1").get(user_id)
        assert saved.birth_time_accuracy == accuracy
        assert saved.birth_place == birth_payload.birth_place
        assert await OnboardingRepository(session, encryption, "v1").get(user_id) is None
    assert (
        await flow(store, encryption, birth_payload).handle(message())
    ).state == State.COMPUTING_PROFILE


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("date", "1991-04-13"),
        ("time", "approximate 12:00"),
        ("place", "Cluj-Napoca, RO"),
    ],
)
async def test_edit_preserves_other_fields_and_invalidates_buttons(
    store, encryption, birth_payload, field, replacement
):
    f = flow(store, encryption, birth_payload)
    await setup_to_time(f)
    await f.handle(message("03:42"))
    places = await f.handle(message("Cluj-Napoca, RO"))
    summary = await f.handle(message(callback=places.buttons[0].data))
    stale_confirm = button(summary, "Confirm profile")
    edited = await f.handle(message(callback=button(summary, f"Edit {field}")))
    assert (await f.handle(message(callback=stale_confirm))).state == edited.state
    summary = await f.handle(message(replacement))
    if field == "place":
        summary = await f.handle(message(callback=summary.buttons[0].data))
    assert summary.state == State.PROFILE_CONFIRMATION
    assert (await f.handle(message(callback=stale_confirm))).state == State.PROFILE_CONFIRMATION
    user_id = await owner(store)
    async with store.transaction() as session:
        draft = await OnboardingRepository(session, encryption, "v1").get(user_id)
        assert str(draft.birth_date) == ("1991-04-13" if field == "date" else "1990-04-13")
        assert draft.birth_time_accuracy == ("approximate" if field == "time" else "exact")
        assert draft.birth_place == birth_payload.birth_place
        assert await session.scalar(select(BirthProfile)) is None


async def test_invalid_inputs_unavailable_and_ambiguous_places(store, encryption, birth_payload):
    f = flow(store, encryption, birth_payload)
    await f.handle(message("1990-04-13"))
    async with store.transaction() as session:
        assert await session.scalar(select(OnboardingProgress)) is None
    await f.handle(message(callback=f.buttons[0].data))
    assert (await f.handle(message("04/05/1990"))).state == State.BIRTH_DATE_REQUIRED
    await f.handle(message("1990-04-13"))
    assert (await f.handle(message("25:00"))).state == State.BIRTH_TIME_REQUIRED
    reply = await f.handle(message("/start"), command="start")
    await f.handle(message(callback=button(reply, "Unknown time")))
    for text in ("email: private@example.test", "Town, Country, street", "Town 123, RO"):
        assert (await f.handle(message(text))).state == State.BIRTH_PLACE_REQUIRED
    f.onboarding.resolver.resolve.assert_not_called()
    f.onboarding.resolver = UnavailablePlaceResolver()
    reply = await f.handle(message("Cluj-Napoca, RO"))
    assert "not available" in reply.text and reply.state == State.BIRTH_PLACE_REQUIRED
    f = flow(store, encryption, birth_payload)
    f.onboarding.resolver.resolve.return_value = ()
    assert "No matching place" in (await f.handle(message("Cluj-Napoca, RO"))).text
    f.onboarding.resolver.resolve.return_value = (
        birth_payload.birth_place,
        birth_payload.birth_place.model_copy(update={"region": "Another region"}),
    )
    reply = await f.handle(message("Cluj-Napoca, RO"))
    assert len(reply.buttons) == 3
    assert (
        await f.handle(message(callback=reply.buttons[1].data))
    ).state == State.PROFILE_CONFIRMATION


async def test_consent_change_blocks_writes_and_invalidates_prior_buttons(
    store, encryption, birth_payload
):
    f = flow(store, encryption, birth_payload)
    time_reply = await setup_to_time(f)
    old_unknown = time_reply.buttons[0].data
    user_id = await owner(store)
    async with store.transaction() as session:
        old_draft = await OnboardingRepository(session, encryption, "v1").get(user_id)
    await f.handle(message(callback=f.buttons[1].data))
    assert (await f.handle(message("03:42"))).state == State.CLOSED
    async with store.transaction() as session:
        with pytest.raises(ConsentRequiredError):
            await OnboardingRepository(session, encryption, "v1").save(user_id, old_draft)
    await f.handle(message(callback=f.buttons[0].data))
    assert (await f.handle(message(callback=old_unknown))).state == State.BIRTH_TIME_REQUIRED
    changed = flow(store, encryption, birth_payload, "v2")
    assert (await changed.handle(message("03:42"))).state == State.CONSENT_REQUIRED
    await changed.handle(message(callback=changed.buttons[0].data))
    assert (await changed.handle(message("unknown"))).state == State.BIRTH_PLACE_REQUIRED


async def test_concurrent_confirmation_and_withdrawal_lock(store, encryption, birth_payload):
    f = flow(store, encryption, birth_payload)
    await setup_to_time(f)
    await f.handle(message("unknown"))
    reply = await f.handle(message("Cluj-Napoca, RO"))
    reply = await f.handle(message(callback=reply.buttons[0].data))
    confirm = button(reply, "Confirm profile")
    user_id = await owner(store)
    async with store.transaction() as session:
        await ConsentRepository(session).revoke(user_id, "telegram")
        pending = asyncio.create_task(f.handle(message(callback=confirm)))
        await asyncio.sleep(0.1)
        assert not pending.done()
    assert (await pending).state == State.CLOSED
    async with store.transaction() as session:
        assert await session.scalar(select(BirthProfile)) is None
    await f.handle(message(callback=f.buttons[0].data))
    reply = await f.handle(message("/start"), command="start")
    confirm = button(reply, "Confirm profile")
    replies = await asyncio.gather(*(f.handle(message(callback=confirm)) for _ in range(2)))
    assert all(r.state == State.COMPUTING_PROFILE for r in replies)
    async with store.transaction() as session:
        assert len(list(await session.scalars(select(BirthProfile)))) == 1


async def test_telegram_collects_commits_before_failed_send_and_logs_no_fields(
    store, encryption, birth_payload, capsys
):
    configure_logging(Settings(_env_file=None))
    f = flow(store, encryption, birth_payload)
    await f.handle(message(callback=f.buttons[0].data))
    bot = Bot("123456:synthetic-test-token", session=AsyncMock())
    client = AsyncMock()
    user_id = await owner(store)

    async def failed_send(*args, **kwargs):
        async with store.transaction() as session:
            draft = await OnboardingRepository(session, encryption, "v1").get(user_id)
            assert str(draft.birth_date) == "1990-04-13"
        raise RuntimeError("1990-04-13 synthetic sensitive failure")

    client.send_text.side_effect = failed_send
    event = Update.model_validate(
        {
            "update_id": 500,
            "message": {
                "message_id": 12,
                "date": 1700000000,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42, "is_bot": False, "first_name": "Synthetic"},
                "text": "1990-04-13",
            },
        }
    )
    await create_dispatcher(client, f).feed_update(bot, event)
    client.send_text.assert_awaited_once()
    assert "1990-04-13" not in capsys.readouterr().err
    restarted = flow(store, encryption, birth_payload)
    assert (
        await restarted.handle(message("/start"), command="start")
    ).state == State.BIRTH_TIME_REQUIRED
