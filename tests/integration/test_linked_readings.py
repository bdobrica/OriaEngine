"""Real owner/consent/CRUD path and calculations, synthetic model replies."""

import json
from uuid import uuid4

import pytest
from astrology_mcp.linked import calculate_event_chart, calculate_synastry

from oria_engine.astrology.client import AstrologyUnavailable
from oria_engine.context.contracts import ContextUnavailable
from oria_engine.context.projections import LinkedContext, recover_projections
from oria_engine.context.service import ConversationContext
from oria_engine.knowledge.contracts import EntityRecord

from .test_knowledge import active, message, saved
from .test_onboarding import store as store
from .test_projections import ProjectionService, provider
from .test_temporal import clear_context as clear_context


async def ready(store, encryption, birth_payload):
    flow, client, remote, user_id = await active(store, encryption, birth_payload)
    client.calculate_synastry.side_effect = calculate_synastry
    client.calculate_event_chart.side_effect = calculate_event_chart
    return flow, client, remote, user_id


async def test_partner_birthday_rating_is_calculated_without_profile_edit_or_transits(
    store,
    encryption,
    birth_payload,
):
    flow, client, remote, user_id = await ready(store, encryption, birth_payload)
    response = await flow.handle(
        message(
            "I'd like you to rate my compatibility with my girlfriend. "
            "Her birthday is June 2nd, 1992"
        )
    )
    assert "Saved" in response.text
    assert client.calculate_synastry.call_count == 1
    client.calculate_transits.assert_not_called()
    request = remote.respond.call_args.args[1]
    assert request.linked_facts.rating is not None
    assert request.linked_facts.charts[1].facts.precision == "date_sample"
    assert not request.linked_facts.charts[1].facts.house_cusps
    assert "1992" not in request.filtered_message and "June" not in request.filtered_message
    assert "no additional calculation was performed" not in request.filtered_message
    assert len(request.linked_facts.sources) == 3  # Own birth, entity, supplied birth.
    assert len(await saved(store, encryption, user_id)) == 2
    assert client.calculate_natal_chart.call_count == 1  # Original own profile only.


async def test_partner_and_wedding_use_three_real_comparisons_and_recalculate_after_correction(
    store,
    encryption,
    birth_payload,
):
    flow, client, remote, user_id = await ready(store, encryption, birth_payload)
    await flow.handle(message("My wife Alice was born June 2nd, 1992"))
    await flow.handle(message("We married May 1st, 2020"))
    await flow.handle(message("Interpret Alice and our wedding chart across all house themes"))
    facts = remote.respond.call_args.args[1].linked_facts
    assert {c.role for c in facts.charts} == {"self", "other", "event"}
    assert len(facts.comparisons) == 3
    assert {4, 7, 8}.issubset(facts.house_themes)
    before = client.calculate_synastry.call_count
    await flow.handle(message("correct our wedding to May 2nd, 2020"))
    await flow.handle(message("Interpret Alice and our wedding chart"))
    new = remote.respond.call_args.args[1].linked_facts
    assert client.calculate_synastry.call_count == before + 3
    old_event = next(r for r in facts.sources if r not in new.sources)
    assert any(r.id == old_event.id and r.revision == old_event.revision + 1 for r in new.sources)
    assert facts.comparisons[1].aspects != new.comparisons[1].aspects


async def test_no_remember_calculates_without_saving_new_partner_inputs(
    store,
    encryption,
    birth_payload,
):
    flow, client, remote, user_id = await ready(store, encryption, birth_payload)
    reply = await flow.handle(
        message(
            "Don't remember this. Rate my compatibility with my girlfriend. "
            "Her birthday is June 2nd, 1992"
        )
    )
    assert "won't add" in reply.text
    assert client.calculate_synastry.call_count == 1
    assert not await saved(store, encryption, user_id)
    assert remote.respond.call_args.args[1].linked_facts is not None


async def test_missing_partner_and_other_owner_do_not_reuse_someone_elses_records(
    store,
    encryption,
    birth_payload,
):
    flow, client, remote, _ = await ready(store, encryption, birth_payload)
    reply = await flow.handle(message("Rate my compatibility with my girlfriend"))
    assert "birth date" in reply.text
    client.calculate_synastry.assert_not_called()
    await flow.handle(message("My girlfriend Alice was born June 2nd, 1992"))
    reply = await flow.handle(message("Rate my compatibility with Zoe"))
    assert "birth date" in reply.text
    client.calculate_synastry.assert_not_called()
    remote.respond.assert_not_called()


async def test_own_supplied_birthday_is_never_bound_to_the_other_chart(
    store,
    encryption,
    birth_payload,
):
    flow, client, remote, _ = await ready(store, encryption, birth_payload)
    reply = await flow.handle(
        message(
            "Don't remember this. I was born April 13th, 1990. "
            "Rate my compatibility with my girlfriend."
        )
    )
    assert "partner's birth date" in reply.text
    client.calculate_synastry.assert_not_called()
    remote.respond.assert_not_called()


async def test_provider_outage_uses_current_calculated_reading_and_harm_never_calls_tools(
    store,
    encryption,
    birth_payload,
):
    flow, client, remote, user_id = await ready(store, encryption, birth_payload)
    await flow.handle(message("My girlfriend Alice was born June 2nd, 1992"))
    remote.respond.side_effect = ContextUnavailable("synthetic-private")
    reply = await flow.handle(message("Rate my compatibility with Alice"))
    assert "/10" in reply.text and "synthetic-private" not in reply.text
    before = client.calculate_synastry.call_count
    reply = await flow.handle(message("How can I hurt my girlfriend? Rate our compatibility"))
    assert "can't help" in reply.text
    assert client.calculate_synastry.call_count == before
    client.calculate_synastry.side_effect = AstrologyUnavailable("synthetic-private")
    with pytest.raises(AstrologyUnavailable):
        await flow.handle(message("Rate my compatibility with Alice"))


async def test_no_remember_new_input_overrides_saved_birthday_for_this_reading_only(
    store,
    encryption,
    birth_payload,
):
    flow, client, remote, user_id = await ready(store, encryption, birth_payload)
    await flow.handle(message("My girlfriend Alice was born June 2nd, 1992"))
    await flow.handle(
        message(
            "Don't remember this. Rate my compatibility with my girlfriend Alice. "
            "Her birthday is June 3rd, 1992"
        )
    )
    assert str(client.calculate_synastry.call_args.args[0].chart_b.calendar_date) == "1992-06-03"
    birth = next(s for s in await saved(store, encryption, user_id) if s.record.kind == "event")
    assert str(birth.record.temporal.value.value) == "1992-06-02"


async def test_birth_date_answer_resumes_the_reading_without_becoming_a_transit(
    store,
    encryption,
    birth_payload,
):
    flow, client, remote, _ = await ready(store, encryption, birth_payload)
    assert (
        "birth date"
        in (await flow.handle(message("Rate my compatibility with my girlfriend"))).text
    )
    reply = await flow.handle(message("June 2nd, 1992"))
    assert "Saved" in reply.text
    assert remote.respond.call_args.args[1].linked_facts.rating is not None
    client.calculate_transits.assert_not_called()


async def test_organization_event_can_support_comparison_without_inventing_a_human_birth(
    store,
    encryption,
    birth_payload,
):
    flow, client, remote, _ = await ready(store, encryption, birth_payload)
    await flow.handle(message("I founded my business Acme on May 1st, 2020"))
    await flow.handle(message("Rate my compatibility with my business"))
    facts = remote.respond.call_args.args[1].linked_facts
    assert facts.rating is not None
    other = next(c for c in facts.charts if c.role == "other")
    assert other.convention == "event" and other.facts.precision == "date_sample"
    client.calculate_transits.assert_not_called()


async def test_birth_date_answer_keeps_unresolved_clock_for_later_refinement(
    store,
    encryption,
    birth_payload,
):
    flow, client, remote, _ = await ready(store, encryption, birth_payload)
    await flow.handle(message("Rate my compatibility with my girlfriend"))
    reply = await flow.handle(message("June 2nd, 1992 at 08:30"))
    assert "Saved" in reply.text
    assert client.calculate_synastry.call_args.args[0].chart_b.accuracy == "unknown"
    assert remote.respond.call_args.args[1].linked_facts.charts[1].facts.precision == "date_sample"
    await flow.handle(message("correct my girlfriend's birth to June 2nd, 1992 at 08:30 UTC"))
    await flow.handle(message("Rate my compatibility with my girlfriend"))
    supplied = client.calculate_synastry.call_args.args[0].chart_b
    assert supplied.accuracy == "exact"
    assert supplied.timestamp_utc.isoformat() == "1992-06-02T08:30:00+00:00"
    assert remote.respond.call_args.args[1].linked_facts is not None
    client.calculate_transits.assert_not_called()


async def test_first_linked_reading_waits_for_source_delivery_and_corrected_memory_is_retired(
    store,
    encryption,
    birth_payload,
):
    flow, client, remote, user_id = await ready(store, encryption, birth_payload)
    service = ProjectionService()
    p = provider(service)
    flow.onboarding.context = ConversationContext(p, "v1")
    try:
        reply = await flow.handle(
            message("Rate my compatibility with my girlfriend. Her birthday is June 2nd, 1992")
        )
        assert "/10" in reply.text and "sample" in reply.text
        assert not any(path.endswith("responses") for path, _ in service.calls)
        async with store.transaction() as session:
            linked = LinkedContext(session, encryption, "v1", p)
            readings = [
                r
                for r in await linked.repo.rows(user_id)
                if not r.deleted and linked.repo.decode(r).knowledge_kind == "interpretation"
            ]
            assert readings and len(linked.repo.decode(readings[0]).sources) == 3
        for _ in range(3):
            await recover_projections(store, encryption, "v1", p)
        await flow.handle(message("Rate my compatibility with my girlfriend"))
        generated = [body for path, body in service.calls if path.endswith("responses")][-1]
        assert generated["knowledge_refs"]
        assert "Calculated linked facts" in generated["instructions"]
        wire = json.dumps(generated)
        assert "1992-06-02" not in wire and "June 2nd" not in wire
        await flow.handle(message("correct my girlfriend's birth to June 3rd, 1992"))
        async with store.transaction() as session:
            linked = LinkedContext(session, encryption, "v1", p)
            readings = [r for r in await linked.repo.rows(user_id) if r.kind == "reading"]
            assert any(r.deleted and r.pending for r in readings)
            assert not await linked.retrieve(user_id, "my girlfriend")
    finally:
        await p.aclose()


async def test_all_sources_must_fit_session_link_contract_before_remote_generation(
    store,
    encryption,
    birth_payload,
):
    flow, client, remote, user_id = await ready(store, encryption, birth_payload)
    await flow.handle(
        message("Rate my compatibility with my girlfriend. Her birthday is June 2nd, 1992")
    )
    request = remote.respond.call_args.args[1]
    service = ProjectionService()
    p = provider(service)
    try:
        async with store.transaction() as session:
            linked = LinkedContext(session, encryption, "v1", p)
            refs = list(request.linked_facts.sources)
            for _ in range(18):
                saved_record = await linked.knowledge.save(
                    user_id,
                    EntityRecord(
                        id=uuid4(),
                        revision=1,
                        entity_type="other",
                        label="Synthetic entity",
                        source_message_id=uuid4(),
                    ),
                )
                refs.append(saved_record.ref)
            await linked.stage(user_id)
        for _ in range(6):
            await recover_projections(store, encryption, "v1", p)
        async with store.transaction() as session:
            linked = LinkedContext(session, encryption, "v1", p)
            rows = await linked.repo.rows(user_id)
            assert not any(r.pending for r in rows)
            calculated = request.linked_facts.model_copy(update={"sources": tuple(refs)})
            reply = await ConversationContext(p, "v1").respond(
                session,
                user_id,
                request.model_copy(update={"linked_facts": calculated}),
                encryption=encryption,
            )
            assert reply.response_id == "oria-linked-local"
            assert not any(path.endswith("responses") for path, _ in service.calls)
    finally:
        await p.aclose()
