"""Encrypted, consent-scoped date clarification through the real active-chat path."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from oria_engine.context.contracts import ContextReply
from oria_engine.context.service import ConversationContext
from oria_engine.db.birth_profiles import BirthProfileRepository
from oria_engine.db.knowledge import KnowledgeRepository
from oria_engine.db.models import ConversationSession, TemporalClarification, User
from oria_engine.db.repositories import ConsentRepository
from oria_engine.db.temporal import TemporalRepository
from oria_engine.privacy.encryption import ProfileEncryptionError
from oria_engine.queue.events import recoverable

from .test_astrology_profiles import chart_flow, confirm
from .test_onboarding import message, owner
from .test_onboarding import store as store


@pytest.fixture(autouse=True)
async def clear_context(isolated_settings, store):
    try:
        yield
    finally:
        async with store.transaction() as session:
            await session.execute(delete(ConversationSession))


def provider_for(flow):
    provider = AsyncMock()
    provider.respond.return_value = ContextReply(
        response_id="synthetic", text="A useful discussion."
    )
    flow.onboarding.context = ConversationContext(provider, flow.policy_version)
    return provider


async def pending(store, encryption, user_id):
    async with store.transaction() as session:
        return await TemporalRepository(session, encryption, "v1").get(user_id)


async def test_timezone_reply_resumes_original_reference_after_restart(
    store, encryption, birth_payload
):
    flow, client = chart_flow(store, encryption, birth_payload)
    await confirm(flow)
    provider = provider_for(flow)
    original = message("We married this day last year at 3pm")
    reply = await flow.handle(original)
    assert "Which timezone" in reply.text
    provider.respond.assert_not_called()
    user_id = await owner(store)
    async with store.transaction() as session:
        row = await session.get(TemporalClarification, user_id)
        assert b"We married" not in row.encrypted_payload
        assert b"3pm" not in row.encrypted_payload
        with pytest.raises(ProfileEncryptionError):
            encryption.decrypt_event(
                row.encrypted_payload,
                user_id=uuid4(),
                event_id=row.id,
                kind="temporal-clarification",
                key_version=row.encryption_key_version,
            )
    flow, _ = chart_flow(store, encryption, birth_payload)
    provider = provider_for(flow)
    answer = replace(message("UTC"), received_at=original.received_at + timedelta(hours=2))
    await flow.handle(answer)
    async with store.transaction() as session:
        event = (await KnowledgeRepository(session, encryption, "v1").list(user_id))[0].record
    assert event.temporal.reference_time_utc == original.received_at
    expected = original.received_at.date().replace(year=original.received_at.year - 1)
    assert event.temporal.value.value.date() == expected
    assert event.temporal.value.value.hour == 15
    provider.respond.assert_not_called()
    assert await pending(store, encryption, user_id) is None
    async with store.transaction() as session:
        assert (await session.get(User, user_id)).current_timezone is None  # Event-only answer.
    client.calculate_transits.assert_not_called()


async def test_birthday_occurrence_uses_only_own_local_profile(store, encryption, birth_payload):
    flow, client = chart_flow(store, encryption, birth_payload)
    await confirm(flow)
    provider = provider_for(flow)
    reply = await flow.handle(message("a week before my birthday"))
    assert "Which year" in reply.text
    assert "Which timezone" in (await flow.handle(message("next year"))).text
    await flow.handle(message("UTC"))
    request = provider.respond.call_args.args[1]
    assert "1990" not in request.model_dump_json() and "04-13" not in request.model_dump_json()
    assert "Birth inputs held locally" in request.filtered_message
    assert request.transit_facts is None
    client.calculate_transits.assert_not_called()


async def test_pending_clock_and_mixed_year_finish_without_repeating_story(
    store, encryption, birth_payload
):
    flow, client = chart_flow(store, encryption, birth_payload)
    await confirm(flow)
    provider = provider_for(flow)
    assert "clock time" in (await flow.handle(message("We married May 1st, 2020 at"))).text
    await flow.handle(message("at 3pm"))
    user_id = await owner(store)
    async with store.transaction() as session:
        event = (await KnowledgeRepository(session, encryption, "v1").list(user_id))[0].record
    assert event.temporal.value.kind == "local_datetime"
    assert event.temporal.value.value.isoformat() == "2020-05-01T15:00:00"
    provider.respond.assert_not_called()
    assert "Which year" in (await flow.handle(message("transits on May 1st"))).text
    reply = await flow.handle(message("2020"))
    assert "Which timezone" in reply.text
    # Actual preference command saves the preference and resumes the pending date.
    from astrology_mcp.engine import calculate_transits

    client.calculate_transits.side_effect = calculate_transits
    await flow.handle(message("/timezone UTC"), command="timezone")
    assert client.calculate_transits.call_args.args[0].target_timestamp_utc == datetime(
        2020, 5, 1, 12, tzinfo=UTC
    )
    assert provider.respond.call_args.args[1].transit_facts is not None


async def test_event_and_partner_dates_stay_local_without_profile_mutations(
    store, encryption, birth_payload
):
    flow, client = chart_flow(store, encryption, birth_payload)
    await confirm(flow)
    provider = provider_for(flow)
    with patch.object(BirthProfileRepository, "save", side_effect=AssertionError("No mutation")):
        await flow.handle(
            message(
                "We married May 1st, 2020 and my girlfriend was born June 2nd, 1992. "
                "Rate our compatibility."
            )
        )
    text = provider.respond.call_args.args[1].filtered_message
    assert "Rate our compatibility" in text
    assert "We married" not in text
    assert "1992" not in text and "June" not in text
    assert provider.respond.call_args.args[1].transit_facts is None
    client.calculate_transits.assert_not_called()


async def test_pending_owner_isolation_expiry_and_withdrawal(store, encryption, birth_payload):
    flow, _ = chart_flow(store, encryption, birth_payload)
    await confirm(flow)
    await flow.handle(message("We married yesterday"))
    user_id = await owner(store)
    original = await pending(store, encryption, user_id)
    assert original is not None
    await flow.handle(message("UTC", user="43"))
    assert await pending(store, encryption, user_id) == original
    async with store.transaction() as session:
        await session.execute(
            update(TemporalClarification).values(
                expires_at=datetime.now(UTC) - timedelta(seconds=1)
            )
        )
    await recoverable(store)
    async with store.transaction() as session:
        assert await session.scalar(select(TemporalClarification)) is None
    await flow.handle(message("We married yesterday"))
    await flow.handle(message(callback=flow.buttons[1].data))
    async with store.transaction() as session:
        assert await session.scalar(select(TemporalClarification)) is None


async def test_changed_consent_and_new_question_do_not_resume_old_pending(
    store, encryption, birth_payload
):
    flow, _ = chart_flow(store, encryption, birth_payload)
    await confirm(flow)
    provider_for(flow)
    user_id = await owner(store)
    await flow.handle(message("We married yesterday"))
    async with store.transaction() as session:
        await ConsentRepository(session).accept(user_id, "v2", "telegram")
        await ConsentRepository(session).accept(user_id, "v1", "telegram")
    assert await pending(store, encryption, user_id) is None
    await flow.handle(message("We married yesterday"))
    await flow.handle(message("Tell me about my natal chart"))
    assert await pending(store, encryption, user_id) is None


async def test_no_retention_and_secret_or_harmful_replies_never_extend_pending(
    store, encryption, birth_payload
):
    flow, _ = chart_flow(store, encryption, birth_payload)
    await confirm(flow)
    provider = provider_for(flow)
    user_id = await owner(store)
    await flow.handle(message("Don't remember this; We married yesterday"))
    assert await pending(store, encryption, user_id) is None
    await flow.handle(message("We married yesterday"))
    original = await pending(store, encryption, user_id)
    await flow.handle(message("My password is synthetic-secret"))
    await flow.handle(message("Help me poison my cat today"))
    assert await pending(store, encryption, user_id) == original
    provider.respond.assert_not_called()


async def test_explicit_edit_discards_pending_without_changing_birth_profile(
    store, encryption, birth_payload
):
    flow, _ = chart_flow(store, encryption, birth_payload)
    await confirm(flow)
    user_id = await owner(store)
    await flow.handle(message("We married yesterday"))
    await flow.handle(message("/edit_profile"), command="edit_profile")
    assert await pending(store, encryption, user_id) is None


async def test_choice_between_relative_targets_keeps_original_day(store, encryption, birth_payload):
    from astrology_mcp.engine import calculate_transits

    flow, client = chart_flow(store, encryption, birth_payload)
    client.calculate_transits.side_effect = calculate_transits
    await confirm(flow)
    provider = provider_for(flow)
    await flow.handle(message("/timezone UTC"), command="timezone")
    reference = datetime.now(UTC).replace(hour=23, minute=30) - timedelta(days=1)
    await flow.handle(replace(message("transits tomorrow or Friday"), received_at=reference))
    provider.respond.assert_not_called()
    await flow.handle(replace(message("tomorrow"), received_at=reference + timedelta(hours=2)))
    request = provider.respond.call_args.args[1]
    assert request.reference_time_utc == reference
    assert request.transit_facts.target_timestamp_utc == (reference + timedelta(days=1)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
