"""Real encrypted canonical memory, conversational CRUD and lifecycle fencing."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from oria_engine.db.birth_profiles import BirthProfileRepository, ConsentRequiredError
from oria_engine.db.knowledge import KnowledgeConflict, KnowledgeRepository
from oria_engine.db.models import (
    KnowledgeChange,
    KnowledgeDialogue,
    KnowledgeLink,
    KnowledgeRecord,
    User,
)
from oria_engine.db.repositories import ConsentRepository, UserRepository, UserUnavailableError
from oria_engine.domain.knowledge import KnowledgeConversation
from oria_engine.knowledge.contracts import (
    CalendarDate,
    EntityRecord,
    EventRecord,
    Participant,
    TemporalEvidence,
)
from oria_engine.privacy.encryption import ProfileEncryptionError
from oria_engine.queue.events import recoverable

from .test_astrology_profiles import chart_flow, confirm
from .test_onboarding import message as base_message
from .test_onboarding import owner
from .test_onboarding import store as store
from .test_temporal import clear_context as clear_context
from .test_temporal import provider_for


def message(text="", **kwargs):
    return replace(base_message(text, **kwargs), provider_update_id=str(uuid4()))


async def saved(store, encryption, user_id):
    async with store.transaction() as session:
        return await KnowledgeRepository(session, encryption, "v1").list(user_id)


async def active(store, encryption, birth_payload):
    flow, client = chart_flow(store, encryption, birth_payload)
    await confirm(flow)
    return flow, client, provider_for(flow), await owner(store)


async def test_learn_restart_inspect_correct_delete_and_no_remote_ingestion(
    store, encryption, birth_payload
):
    flow, client, provider, user_id = await active(store, encryption, birth_payload)
    original = message("We married May 1st, 2020")
    assert "Saved" in (await flow.handle(original)).text
    records = await saved(store, encryption, user_id)
    wedding = records[0]
    assert wedding.record.temporal.value == CalendarDate(value=date(2020, 5, 1))
    async with store.transaction() as session:
        row = await session.get(KnowledgeRecord, (user_id, wedding.ref.id))
        assert b"wedding" not in row.encrypted_payload and b"2020" not in row.encrypted_payload
        with pytest.raises(ProfileEncryptionError):
            encryption.decrypt_event(
                row.encrypted_payload,
                user_id=uuid4(),
                event_id=row.id,
                kind="knowledge-event-r1",
                key_version=row.encryption_key_version,
            )
    flow, _ = chart_flow(store, encryption, birth_payload)
    assert (
        "2020-05-01" in (await flow.handle(message("what do you remember about our wedding?"))).text
    )
    assert "2020-05-02" in (await flow.handle(message("it was May 2nd, not May 1st"))).text
    changed = (await saved(store, encryption, user_id))[0]
    assert changed.record.id == wedding.record.id and changed.record.revision == 2
    async with store.transaction() as session:
        assert len((await session.scalars(select(KnowledgeChange))).all()) == 2
        assert (
            await KnowledgeRepository(session, encryption, "v1").get(user_id, wedding.ref) is None
        )
    assert "Removed 1" in (await flow.handle(message("forget our wedding"))).text
    assert not await saved(store, encryption, user_id)
    # Replaying an old input cannot recreate the erased record or save a new UUID.
    assert "already processed" in (await flow.handle(original)).text
    assert not await saved(store, encryption, user_id)
    async with store.transaction() as session:
        fence = await session.get(KnowledgeRecord, (user_id, wedding.ref.id))
        assert fence.deleted_at and fence.revision == 3 and fence.encrypted_payload is None
        assert await session.scalar(select(KnowledgeChange)) is None
        assert await session.scalar(select(KnowledgeDialogue)) is None
    provider.respond.assert_not_called()
    provider.remember.assert_not_called()
    client.calculate_transits.assert_not_called()


async def test_entities_aliases_partial_dates_and_pronoun_continuity(
    store, encryption, birth_payload
):
    flow, client, provider, user_id = await active(store, encryption, birth_payload)
    assert "Alice" in (await flow.handle(message("My girlfriend is Alice"))).text
    assert "Saved" in (await flow.handle(message("Her birthday is June 2nd, 1992"))).text
    records = await saved(store, encryption, user_id)
    entity = next(s for s in records if s.record.kind == "entity")
    birth = next(s for s in records if s.record.kind == "event")
    assert entity.record.label == "Alice" and "my girlfriend" in entity.record.aliases
    assert birth.record.participants[0].entity_id == entity.record.id
    assert (
        "1992-06-02"
        in (await flow.handle(message("what do you remember about my girlfriend's birthday?"))).text
    )
    # Same mention is deduplicated even under a new ingress ID.
    await flow.handle(message("My girlfriend Alice was born June 2nd, 1992"))
    assert len(await saved(store, encryption, user_id)) == 2
    with patch.object(BirthProfileRepository, "save", side_effect=AssertionError("No own edit")):
        assert (
            "Updated"
            in (await flow.handle(message("correct Alice's birth to June 3rd, 1992"))).text
        )
    assert client.calculate_transits.call_count == 0
    provider.respond.assert_not_called()


async def test_multiple_entities_events_owner_isolation_and_erasure_cascade(
    store, encryption, birth_payload
):
    flow, _, provider, user_id = await active(store, encryption, birth_payload)
    await flow.handle(
        message(
            "My girlfriend Alice was born June 2nd, 1992 and I adopted my cat Luna on May 1st, 2020"
        )
    )
    records = await saved(store, encryption, user_id)
    assert len(records) == 4
    assert (
        "don't have a saved"
        in (await flow.handle(message("what do you remember about Alice?", user="43"))).text
    )
    assert "Remove them too" in (await flow.handle(message("forget my girlfriend"))).text
    assert len(await saved(store, encryption, user_id)) == 4
    assert "Removed 2" in (await flow.handle(message("yes"))).text
    remaining = await saved(store, encryption, user_id)
    assert len(remaining) == 2 and any(
        s.record.kind == "entity" and s.record.label == "Luna" for s in remaining
    )
    provider.respond.assert_not_called()


async def test_ambiguous_occurrences_and_new_entity_names_are_not_merged(
    store, encryption, birth_payload
):
    flow, _, _, user_id = await active(store, encryption, birth_payload)
    await flow.handle(message("We married May 1st, 2020"))
    assert "another event" in (await flow.handle(message("We married May 2nd, 2021"))).text
    assert len(await saved(store, encryption, user_id)) == 1
    assert "Saved" in (await flow.handle(message("another event"))).text
    assert len(await saved(store, encryption, user_id)) == 2
    assert "Which saved record" in (await flow.handle(message("forget our wedding"))).text
    flow, _ = chart_flow(store, encryption, birth_payload)
    assert "Removed 1" in (await flow.handle(message("1"))).text
    assert len(await saved(store, encryption, user_id)) == 1
    await flow.handle(message("My girlfriend Alice was born June 2nd, 1992"))
    assert (
        "Which entity"
        in (await flow.handle(message("My girlfriend Beth was born June 2nd, 1993"))).text
    )
    assert not any(
        s.record.kind == "entity" and s.record.label == "Beth"
        for s in await saved(store, encryption, user_id)
    )
    await flow.handle(message("another person"))
    assert any(
        s.record.kind == "entity" and s.record.label == "Beth"
        for s in await saved(store, encryption, user_id)
    )


async def test_no_remember_examples_secrets_and_withdrawal_controls(
    store, encryption, birth_payload
):
    flow, _, provider, user_id = await active(store, encryption, birth_payload)
    for text in [
        "Don't remember this; we married May 1st, 2020",
        "If we married May 1st, 2020",
        "We did not marry in 2020",
        "My password is synthetic-secret",
    ]:
        await flow.handle(message(text))
    assert not await saved(store, encryption, user_id)
    await flow.handle(message("We married May 1st, 2020"))
    await flow.handle(message(callback=flow.buttons[1].data))
    assert (
        "2020-05-01" in (await flow.handle(message("what do you remember about our wedding?"))).text
    )
    assert "Removed 1" in (await flow.handle(message("forget our wedding"))).text
    await flow.handle(message("We married May 2nd, 2020"))
    assert not await saved(store, encryption, user_id)
    async with store.transaction() as session:
        with pytest.raises(ConsentRequiredError):
            await KnowledgeRepository(session, encryption, "v1").save(
                user_id,
                EntityRecord(
                    id=uuid4(),
                    revision=1,
                    entity_type="person",
                    label="Synthetic",
                    source_message_id=uuid4(),
                ),
            )


async def test_relative_events_clarify_then_recall_original_date_and_anchor(
    store, encryption, birth_payload
):
    flow, _, provider, user_id = await active(store, encryption, birth_payload)
    reference = datetime.now(UTC) - timedelta(hours=1)
    first = replace(message("We married this day last year at 3pm"), received_at=reference)
    assert "Which timezone" in (await flow.handle(first)).text
    assert not await saved(store, encryption, user_id)
    assert "Saved" in (await flow.handle(message("UTC"))).text
    record = (await saved(store, encryption, user_id))[0].record
    assert record.temporal.reference_time_utc == reference
    assert record.temporal.value.value.date() == reference.date().replace(year=reference.year - 1)
    assert (await flow.handle(message("what do you remember about our wedding?"))).text.count(
        "15:00"
    ) == 1
    async with store.transaction() as session:
        anchors = await KnowledgeConversation(session, encryption, "v1").anchors(user_id)
        assert any(a.label == "our wedding day" and a.reference.id == record.id for a in anchors)
    provider.respond.assert_not_called()


async def test_repository_reference_fences_cross_owner_links_and_invalidation(
    store, encryption, birth_payload
):
    flow, _, _, user_id = await active(store, encryption, birth_payload)
    await flow.handle(message("We married May 1st, 2020"))
    wedding = (await saved(store, encryption, user_id))[0]
    async with store.transaction() as session:
        other = await UserRepository(session).create()
        await ConsentRepository(session).accept(other.id, "v1", "telegram")
        repo = KnowledgeRepository(session, encryption, "v1")
        assert await repo.get(other.id, wedding.ref) is None
        other_entity = await repo.save(
            other.id,
            EntityRecord(
                id=uuid4(),
                revision=1,
                entity_type="person",
                label="Synthetic",
                source_message_id=uuid4(),
            ),
        )
        with pytest.raises(KnowledgeConflict):
            await repo.save(
                user_id,
                EventRecord(
                    id=uuid4(),
                    revision=1,
                    event_type="test",
                    description="test",
                    source_message_id=uuid4(),
                    participants=(Participant(entity_id=other_entity.record.id, role="person"),),
                ),
            )
    async with store.transaction() as session:
        repo = KnowledgeRepository(session, encryption, "v1")
        evidence = TemporalEvidence(
            expression="a week after our wedding day",
            reference_time_utc=datetime.now(UTC),
            resolution_version="test",
            anchor=wedding.ref,
            value=CalendarDate(value=date(2020, 5, 8)),
        )
        dependent = await repo.save(
            user_id,
            EventRecord(
                id=uuid4(),
                revision=1,
                event_type="trip",
                description="our trip",
                source_message_id=uuid4(),
                temporal=evidence,
            ),
        )
    await flow.handle(message("correct our wedding to May 2nd, 2020"))
    async with store.transaction() as session:
        repo = KnowledgeRepository(session, encryption, "v1")
        assert (await repo.get(user_id, dependent.ref)).needs_review
        with pytest.raises(KnowledgeConflict):
            await repo.save(user_id, wedding.record.model_copy(update={"revision": 2}))
    assert (
        "date needs confirmation"
        in (await flow.handle(message("what do you remember about our trip?"))).text
    )


async def test_expiry_and_concurrent_withdrawal_write_fence(store, encryption, birth_payload):
    flow, _, _, user_id = await active(store, encryption, birth_payload)
    await flow.handle(message("We married May 1st, 2020"))
    async with store.transaction() as session:
        await session.execute(
            update(KnowledgeDialogue).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    await recoverable(store)
    async with store.transaction() as session:
        assert await session.scalar(select(KnowledgeDialogue)) is None
    locked = asyncio.Event()
    release = asyncio.Event()

    async def withdrawal():
        async with store.transaction() as session:
            await ConsentRepository(session).revoke(user_id, "telegram")
            locked.set()
            await release.wait()

    async def write():
        await locked.wait()
        async with store.transaction() as session:
            with pytest.raises(ConsentRequiredError):
                await KnowledgeRepository(session, encryption, "v1").save(
                    user_id,
                    EntityRecord(
                        id=uuid4(),
                        revision=1,
                        entity_type="other",
                        label="late",
                        source_message_id=uuid4(),
                    ),
                )

    first = asyncio.create_task(withdrawal())
    second = asyncio.create_task(write())
    await locked.wait()
    await asyncio.sleep(0.02)
    assert not second.done()
    release.set()
    await asyncio.gather(first, second)


async def test_no_invented_times_unknown_dates_and_custom_event_types(
    store, encryption, birth_payload
):
    flow, _, provider, user_id = await active(store, encryption, birth_payload)
    await flow.handle(message("I bought my house in May 2020"))
    await flow.handle(message("I founded my business"))
    await flow.handle(message("Remember that I won a prize in 2021"))
    records = await saved(store, encryption, user_id)
    events = [s.record for s in records if s.record.kind == "event"]
    assert len(events) == 3
    purchase = next(r for r in events if r.event_type == "purchase")
    assert purchase.temporal.value.kind == "partial_date"
    assert purchase.temporal.value.year == 2020 and purchase.temporal.value.day is None
    assert next(r for r in events if r.event_type == "founding").temporal is None
    provider.respond.assert_not_called()


async def test_conversational_alias_rename_former_relationship_and_split(
    store, encryption, birth_payload
):
    flow, _, _, user_id = await active(store, encryption, birth_payload)
    await flow.handle(message("My girlfriend Alice was born June 2nd, 1992"))
    entity = next(s for s in await saved(store, encryption, user_id) if s.record.kind == "entity")
    assert "Updated" in (await flow.handle(message("correct Alice name to Alicia"))).text
    assert (
        "Updated"
        in (await flow.handle(message("correct Alicia relationship to ex-girlfriend"))).text
    )
    assert (
        "1992-06-02"
        in (await flow.handle(message("what do you remember about Alicia's birthday?"))).text
    )
    changed = next(s for s in await saved(store, encryption, user_id) if s.record.kind == "entity")
    assert changed.record.id == entity.record.id and changed.record.revision == 3
    assert changed.record.relationship_to_user == "ex-girlfriend"
    assert (
        "my girlfriend" not in changed.record.aliases
        and "my ex-girlfriend" in changed.record.aliases
    )
    # A new current relationship is a new entity, not a merge with the former one.
    await flow.handle(message("My girlfriend Beth was born June 2nd, 1993"))
    assert (
        len([s for s in await saved(store, encryption, user_id) if s.record.kind == "entity"]) == 2
    )
    assert "Removed 1" in (await flow.handle(message("forget my ex-girlfriend's birthday"))).text
    assert any(
        s.record.kind == "event" and s.record.temporal.value.value.year == 1993
        for s in await saved(store, encryption, user_id)
    )


async def test_pending_correction_and_ambiguous_anchor_keep_selected_record(
    store, encryption, birth_payload
):
    flow, _, provider, user_id = await active(store, encryption, birth_payload)
    await flow.handle(message("We married May 1st, 2020"))
    assert "correct date" in (await flow.handle(message("correct our wedding"))).text
    assert "Updated" in (await flow.handle(message("May 2nd, 2020"))).text
    await flow.handle(message("We married May 3rd, 2021"))
    await flow.handle(message("another event"))
    assert (
        "Which saved occurrence"
        in (await flow.handle(message("a week before our wedding day"))).text
    )
    answer = await flow.handle(message("1"))
    # No calculation request and no new fact: resolving the expression is ordinary context.
    assert "Which saved occurrence" not in answer.text
    assert len(await saved(store, encryption, user_id)) == 2


async def test_own_birth_is_a_profile_reference_and_erasure_covers_derived_copies(
    store, encryption, birth_payload
):
    from oria_engine.db.models import AstrologyProfile, BirthProfile, OnboardingProgress

    flow, _, _, user_id = await active(store, encryption, birth_payload)
    async with store.transaction() as session:
        repo = KnowledgeRepository(session, encryption, "v1")
        own_birth = await repo.own_birth(user_id)
        assert own_birth.record.natal_profile_revision == 1
        event = await repo.save(
            user_id,
            EventRecord(
                id=uuid4(),
                revision=1,
                event_type="celebration",
                description="first celebration",
                source_message_id=uuid4(),
                temporal=TemporalEvidence(
                    expression="a week after the day I was born",
                    reference_time_utc=datetime.now(UTC),
                    resolution_version="test",
                    anchor=own_birth.ref,
                    value=CalendarDate(value=date(1990, 4, 20)),
                ),
            ),
        )
    # Updating the canonical profile invalidates dependent resolutions without copying inputs.
    async with store.transaction() as session:
        await BirthProfileRepository(session, encryption, policy_version="v1").save(
            user_id, birth_payload
        )
    async with store.transaction() as session:
        repo = KnowledgeRepository(session, encryption, "v1")
        assert await repo.get(user_id, own_birth.ref) is None
        assert (await repo.own_birth(user_id)).record.natal_profile_revision == 2
        assert (await repo.get(user_id, event.ref)).needs_review
    await flow.handle(message(callback=flow.buttons[1].data))
    assert (
        "1990-04-13" in (await flow.handle(message("what do you remember about my birthday?"))).text
    )
    assert "Remove them too" in (await flow.handle(message("forget my birthday"))).text
    assert "Removed 2" in (await flow.handle(message("yes"))).text
    async with store.transaction() as session:
        for model in (BirthProfile, AstrologyProfile, OnboardingProgress):
            assert await session.scalar(select(model).where(model.user_id == user_id)) is None
    assert not await saved(store, encryption, user_id)


async def test_database_edges_cannot_cross_owner_and_ciphertext_cannot_change_revision(
    store, encryption, birth_payload
):
    from sqlalchemy.exc import IntegrityError

    flow, _, _, user_id = await active(store, encryption, birth_payload)
    await flow.handle(message("We married May 1st, 2020"))
    record = (await saved(store, encryption, user_id))[0]
    async with store.transaction() as session:
        other = await UserRepository(session).create()
        await ConsentRepository(session).accept(other.id, "v1", "telegram")
        other_record = await KnowledgeRepository(session, encryption, "v1").save(
            other.id,
            EntityRecord(
                id=uuid4(),
                revision=1,
                entity_type="person",
                label="Synthetic",
                source_message_id=uuid4(),
            ),
        )
        async with session.begin_nested() as nested:
            with pytest.raises(IntegrityError):
                session.add(
                    KnowledgeLink(
                        user_id=user_id, record_id=record.ref.id, dependency_id=other_record.ref.id
                    )
                )
                await session.flush()
            await nested.rollback()
    async with store.transaction() as session, session.begin_nested() as nested:
        row = await session.get(KnowledgeRecord, (user_id, record.ref.id))
        row.revision += 1
        await session.flush()
        with pytest.raises(ProfileEncryptionError):
            await KnowledgeRepository(session, encryption, "v1").list(user_id)
        await nested.rollback()


async def test_explicit_reading_continues_and_failed_calculation_cannot_acknowledge_save(
    store, encryption, birth_payload
):
    from astrology_mcp.linked import calculate_synastry

    from oria_engine.astrology.client import AstrologyUnavailable

    flow, client, provider, user_id = await active(store, encryption, birth_payload)
    client.calculate_synastry.side_effect = AstrologyUnavailable("synthetic")
    text = message("My girlfriend Alice was born June 2nd, 1992. Rate our compatibility.")
    with pytest.raises(AstrologyUnavailable):
        await flow.handle(text)
    assert not await saved(store, encryption, user_id)
    provider.respond.assert_not_called()
    client.calculate_synastry.side_effect = calculate_synastry
    reply = await flow.handle(text)
    assert "Saved" in reply.text and "A useful discussion" in reply.text
    assert "1992-06-02" not in provider.respond.call_args.args[1].model_dump_json()
    assert provider.respond.call_args.args[1].linked_facts.rating is not None
    assert "Rate our compatibility" in provider.respond.call_args.args[1].filtered_message
    assert len(await saved(store, encryption, user_id)) == 2


async def test_deleted_owner_cannot_save_and_pending_focus_does_not_leak(
    store, encryption, birth_payload
):
    flow, _, _, user_id = await active(store, encryption, birth_payload)
    await flow.handle(message("My girlfriend Alice was born June 2nd, 1992"))
    async with store.transaction() as session:
        row = await session.get(KnowledgeDialogue, user_id)
        assert b"Alice" not in row.encrypted_payload
        with pytest.raises(ProfileEncryptionError):
            encryption.decrypt_event(
                row.encrypted_payload,
                user_id=uuid4(),
                event_id=row.id,
                kind="knowledge-dialogue",
                key_version=row.encryption_key_version,
            )
        user = await session.get(User, user_id)
        user.deleted_at = datetime.now(UTC)
    async with store.transaction() as session:
        with pytest.raises(UserUnavailableError):
            await KnowledgeRepository(session, encryption, "v1").save(
                user_id,
                EntityRecord(
                    id=uuid4(),
                    revision=1,
                    entity_type="other",
                    label="late",
                    source_message_id=uuid4(),
                ),
            )


async def test_explicit_place_is_kept_without_inventing_coordinates_or_zone(
    store, encryption, birth_payload
):
    flow, _, provider, user_id = await active(store, encryption, birth_payload)
    await flow.handle(
        message("My girlfriend alice was born June 2nd, 1992 at 15:30 in Exampletown")
    )
    records = await saved(store, encryption, user_id)
    event = next(s.record for s in records if s.record.kind == "event")
    assert event.place == "Exampletown"
    assert event.temporal.value.kind == "local_datetime"
    assert event.temporal.timezone is None
    provider.respond.assert_not_called()


async def test_date_then_record_clarification_preserves_clock_zone_and_original_operation(
    store, encryption, birth_payload
):
    from oria_engine.domain.knowledge import source_id

    flow, _, _, user_id = await active(store, encryption, birth_payload)
    await flow.handle(message("We married May 1st, 2020"))
    original = replace(
        message("We married this day last year at 3pm"),
        received_at=datetime.now(UTC) - timedelta(hours=1),
    )
    assert "Which timezone" in (await flow.handle(original)).text
    assert "another event" in (await flow.handle(message("UTC"))).text
    reply = await flow.handle(message("another event"))
    assert "Saved" in reply.text
    records = await saved(store, encryption, user_id)
    assert len(records) == 2
    new = next(
        s.record for s in records if s.record.source_message_id == source_id(user_id, original)
    )
    assert new.temporal.reference_time_utc == original.received_at
    assert new.temporal.timezone == "UTC" and new.temporal.timezone_source == "explicit_event"
    assert new.temporal.value.value.hour == 15


async def test_corrections_preserve_approximation_and_supplied_place(
    store, encryption, birth_payload
):
    flow, _, _, user_id = await active(store, encryption, birth_payload)
    await flow.handle(message("We married May 1st, 2020 in Exampletown"))
    assert "Updated" in (await flow.handle(message("correct our wedding place to Otherplace"))).text
    reply = await flow.handle(message("it was around May 2nd, not May 1st"))
    assert "Updated" in reply.text
    record = (await saved(store, encryption, user_id))[0].record
    assert record.place == "Otherplace"
    assert record.temporal.value.approximate is True
    assert record.temporal.value.value == date(2020, 5, 2)


async def test_starting_birth_profile_edit_discards_suspended_memory_selection(
    store, encryption, birth_payload
):
    flow, _, _, user_id = await active(store, encryption, birth_payload)
    await flow.handle(message("We married May 1st, 2020"))
    assert "another event" in (await flow.handle(message("We married May 2nd, 2021"))).text
    async with store.transaction() as session:
        assert await session.get(KnowledgeDialogue, user_id) is not None
    await flow.handle(message("/edit_profile"), command="edit_profile")
    async with store.transaction() as session:
        assert await session.get(KnowledgeDialogue, user_id) is None
    assert len(await saved(store, encryption, user_id)) == 1
