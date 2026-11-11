"""Synthetic dialogue through Oria workers and the real SecondContext HTTP gateway."""

import asyncio
import json
from datetime import UTC, datetime, time, timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from oria_engine.context.contracts import ContextReply, ContextScope, ConversationRequest
from oria_engine.context.history import AcceptGenerated, HistoryFailure, HistoryUnsupported
from oria_engine.context.history_workflow import capture_local
from oria_engine.context.projections import recover_projections
from oria_engine.db.birth_profiles import BirthProfileRepository
from oria_engine.db.models import ContextProjectionWork, DeletionJob, InboundEvent
from oria_engine.domain.channel import DeliveryRejected
from oria_engine.domain.policy import PRIVACY_REPLY
from oria_engine.privacy.deletion import DeletionWorker
from oria_engine.queue.events import EventWorker, recoverable
from tests.integration.test_history_workflow import cleanup, work_row
from tests.integration.test_queue import due, message, row

GENERATE = "/v1/responses"
FINALIZE = "/v1/context/turns/finalize"


async def send(harness, text, *, command=None, callback=None):
    ingress, worker, *_ = harness
    event_id = await ingress.accept(message(text=text, callback=callback), command=command)
    await worker.process(event_id)
    assert (await row(worker, event_id)).status == "sent", harness[3].statuses
    return event_id, worker.client.send_text.call_args.args[1]


def assert_input(model, exchanges, current):
    """Full dialogue equality catches extra drafts, duplicated turns and foreign context."""
    messages = model.calls[-1]["messages"]
    assert messages[0]["role"] == "system"
    assert "untrusted historical dialogue" in messages[0]["content"]
    expected = []
    for user, assistant in exchanges:
        expected.extend(
            [
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            ]
        )
    expected.append({"role": "user", "content": current})
    assert messages[1:] == expected


@pytest.mark.parametrize("real_history", ["unprojected"], indirect=True)
async def test_first_transit_reading_and_followup_fit_deployment_budget(real_history):
    _, worker, model, wire, _, _ = real_history
    await send(real_history, "/timezone Europe/Bucharest", command="timezone")
    model.reply = "Today's closest contacts suggest making time for a calm conversation."
    first, reply = await send(real_history, "How is my day going today?")
    assert model.calls and model.reply in reply and reply.startswith("Snapshot:")
    assert (await work_row(worker, first)).receipt
    current = wire.bodies(GENERATE)[-1]["input"]
    assert_input(model, [], current)
    model.reply = "By that I mean giving each person time to finish their thoughts."
    await send(real_history, "What does it mean?")
    assert_input(model, [(current, reply)], "What does it mean?")
    await send(real_history, "I'd like to know what today's horoscope brings me.")
    await send(real_history, "transits on 2026-11-12")
    assert len(model.calls) == 4
    assert model.reply in worker.client.send_text.call_args.args[1]
    largest = max(len(json.dumps(call, ensure_ascii=False).encode()) + 128 for call in model.calls)
    assert 32768 < largest <= 65536


@pytest.mark.parametrize("observe", [False, True])
async def test_private_compatibility_reading_hands_off_to_plain_english_followup(
    real_history, observe
):
    _, worker, model, wire, gateway, user_id = real_history
    if observe:
        gateway.env.update(
            DECISIONS_OBSERVE_ENABLED="true",
            DECISIONS_BASE_URL=gateway.env["OPENAI_BASE_URL"],
            DECISIONS_API_KEY=gateway.env["OPENAI_API_KEY"],
            DECISIONS_CACHE_SECRET=uuid4().hex + uuid4().hex,
        )
        await gateway.restart()
    await send(real_history, "/timezone Europe/Bucharest", command="timezone")
    model.reply = "Tomorrow's reading suggests taking time to reflect."
    await send(real_history, "How is tomorrow looking?")
    await send(real_history, "What does it mean?")
    _, question = await send(real_history, "What's my compatibility with my girlfriend?")
    assert "partner's birth date" in question
    _, local = await send(real_history, "1992-06-02")
    assert "Saved" in local and "alongside" in local
    assert len(model.calls) == 2  # Private clarification and receipt stay local.
    assert len(model.decisions) == (2 if observe else 0)
    model.reply = "In this relationship, you may bring different strengths to shared plans."
    event_id, reply = await send(real_history, "What does it mean in plain English?")
    current = wire.bodies(GENERATE)[-1]
    assert "Regarding the compatibility reading:" in current["input"]
    assert "Calculated linked facts" in current["instructions"]
    assert '"kind":"compatibility"' in current["instructions"]
    assert "Calculated transit facts" not in current["instructions"]
    assert len(current["knowledge_refs"]) >= 3
    assert reply == model.reply and (await work_row(worker, event_id)).receipt
    assert "1992-06-02" not in json.dumps(model.calls)
    assert "Saved in your private profile" not in json.dumps(model.calls)
    if observe:
        observed = model.decisions[-1]["input"][0]["content"][-1]["text"]
        assert "Regarding the compatibility reading:" in observed
        assert "Calculated linked facts" in observed
        assert "1992-06-02" not in json.dumps(model.decisions)
        assert "Saved in your private profile" not in json.dumps(model.decisions)
        assert len(model.calls[-1]["messages"]) > 2  # Standalone prediction did not trim.
    await send(real_history, "Switch topics: how do rainbows form?")
    await send(real_history, "Tell me more")
    assert "Calculated linked facts" not in wire.bodies(GENERATE)[-1]["instructions"]
    assert wire.bodies(GENERATE)[-1]["input"] == "Tell me more"
    assert len(model.decisions) == (len(model.calls) if observe else 0)
    if observe:
        latest = model.decisions[-1]["input"][0]["content"][-1]["text"]
        assert "Tell me more" in latest
        assert "Calculated linked facts" not in latest


async def test_exact_followups_options_corrections_topic_changes_and_recent_bound(real_history):
    _, _, model, wire, _, _ = real_history
    exchanges = []
    inputs = [
        "Suggest two ways to reflect",
        "Tell me more",
        "The second one",
        "Actually, I meant the first option",
        "Switch topics: how do rainbows form?",
        "Why?",
        "Give an example",
        "Make it shorter",
        "And another example",
        "Explain that",
    ]
    for index, text in enumerate(inputs):
        model.reply = f"Synthetic conversational reply {index}."
        _, reply = await send(real_history, text)
        assert_input(model, exchanges[-8:], text)
        # Current calculated facts/instructions remain a single current system message.
        assert (
            wire.bodies(GENERATE)[-1]["instructions"] in model.calls[-1]["messages"][0]["content"]
        )
        exchanges.append((text, reply))
    assert len(model.calls) == len(inputs)


async def test_sessions_and_accounts_do_not_share_dialogue(real_history):
    _, worker, model, _, _, user_id = real_history
    await send(real_history, "Discuss a quiet walk")
    provider = worker.history_provider
    for owner in (user_id, uuid4()):
        scope = ContextScope(user_id=owner, session_id=uuid4())
        prepared = provider.prepare_history_turn(
            scope,
            ConversationRequest(filtered_message="An unrelated conversation"),
            turn_id=uuid4(),
        )
        await provider.respond_history(scope, prepared)
        assert_input(model, [], "An unrelated conversation")


async def test_replacement_not_draft_and_duplicate_ingress_replay_once(real_history):
    ingress, worker, model, _, _, _ = real_history
    model.reply = "Tell me your email."
    inbound = message(text="Suggest two approaches")
    ids = await asyncio.gather(*(ingress.accept(inbound) for _ in range(3)))
    assert len(set(ids)) == 1
    await asyncio.gather(*(worker.process(ids[0]) for _ in range(3)))
    assert (await row(worker, ids[0])).status == "sent"
    model.reply = "A short reflective answer."
    await send(real_history, "Tell me more")
    assert_input(model, [(inbound.text, PRIVACY_REPLY)], "Tell me more")
    assert len(model.calls) == 2
    assert "Tell me your email." not in json.dumps(model.calls[-1])


@pytest.mark.parametrize("lost_path", [GENERATE, FINALIZE])
async def test_lost_ack_restart_and_interrupted_recovery_reuse_one_turn(real_history, lost_path):
    ingress, worker, model, wire, gateway, _ = real_history
    wire.lose.add(lost_path)
    event_id = await ingress.accept(message(text="Suggest two approaches"))
    await worker.process(event_id)
    assert (await row(worker, event_id)).status == ("pending" if lost_path == GENERATE else "ready")
    worker.client.send_text.assert_not_called()
    await gateway.restart()
    restarted = EventWorker(
        worker.database,
        worker.redis,
        worker.encryption,
        worker.flow,
        worker.client,
        history_provider=worker.history_provider,
        history_enabled=True,
    )
    # Recovery itself loses its acknowledgement again; no additional model call.
    await due(worker, event_id)
    await restarted.process(event_id)
    wire.lose.clear()
    await due(worker, event_id)
    await restarted.process(event_id)
    assert (await row(worker, event_id)).status == "sent"
    bodies = wire.bodies(lost_path)
    assert len(bodies) == 3 and bodies[0] == bodies[1] == bodies[2]
    assert len(model.calls) == 1
    reply = worker.client.send_text.call_args.args[1]
    await send(real_history, "The second one")
    assert_input(model, [("Suggest two approaches", reply)], "The second one")


async def test_gateway_crash_during_generation_recovers_same_snapshot(real_history):
    ingress, worker, model, wire, gateway, _ = real_history
    first = await ingress.accept(message(text="Suggest two approaches"))
    model.release.clear()
    task = asyncio.create_task(worker.process(first))
    try:
        await asyncio.wait_for(model.entered.wait(), timeout=10)
        await gateway.stop()
        await asyncio.wait_for(task, timeout=10)
    finally:
        model.release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert (await work_row(worker, first)).phase == "prepared"
    await gateway.start()
    await due(worker, first)
    await worker.process(first)
    assert (await row(worker, first)).status == "sent"
    assert wire.bodies(GENERATE)[0] == wire.bodies(GENERATE)[1]
    # A crash before durable completion can repeat provider execution, with the same input.
    assert len(model.calls) == 2 and model.calls[0] == model.calls[1]
    reply = worker.client.send_text.call_args.args[1]
    await send(real_history, "The first one")
    assert_input(model, [("Suggest two approaches", reply)], "The first one")


@pytest.mark.parametrize(
    "failure,delivery",
    [(DeliveryRejected("synthetic"), "failed"), (RuntimeError("synthetic"), "unknown")],
)
async def test_delivery_exhaustion_preserves_acceptance_order_and_uncertainty(
    real_history, failure, delivery
):
    ingress, worker, model, _, _, _ = real_history
    first = await ingress.accept(message(text="Suggest two approaches"))
    second = await ingress.accept(message(text="The second one"))
    worker.client.send_text.side_effect = failure
    await worker.process(first)
    await worker.process(second)
    assert len(model.calls) == 1
    assert (await row(worker, second)).attempts == 0
    for _ in range(4):
        await due(worker, first)
        await worker.process(first)
    assert (await row(worker, first)).status == "dead"
    work = await work_row(worker, first)
    assert work.receipt and work.delivery == delivery
    worker.client.send_text.side_effect = None
    await worker.process(second)
    assert (await row(worker, second)).status == "sent"
    assert_input(model, [("Suggest two approaches", model.reply)], "The second one")
    assert "unconfirmed channel delivery" in model.calls[-1]["messages"][0]["content"]
    assert len(model.calls) == 2


async def test_local_question_answer_and_calculated_reading_replay(real_history):
    _, worker, model, wire, _, _ = real_history
    context = worker.flow.onboarding.context

    async def local_question(session, user_id, request, **kwargs):
        text = "Would you prefer a brief reflection or a detailed one?"
        await capture_local(session, request, text)
        return ContextReply(response_id="synthetic-local", text=text)

    # An explicitly allowlisted ordinary-question consumer, using the actual capture lane.
    with patch.object(context, "respond", side_effect=local_question):
        _, question = await send(real_history, "Help me choose an approach")
    assert not model.calls
    _, answer = await send(real_history, "A brief reflection")
    assert_input(model, [("Help me choose an approach", question)], "A brief reflection")
    worker.flow.onboarding.context = None  # Actual deterministic calculated branch.
    _, reading = await send(real_history, "Explain my natal chart")
    worker.flow.onboarding.context = context
    assert wire.bodies(FINALIZE)[-1]["action"] == "accept_local"
    assert wire.bodies(FINALIZE)[-1]["knowledge_refs"]
    await send(real_history, "Tell me more")
    assert_input(
        model,
        [
            ("Help me choose an approach", question),
            ("A brief reflection", answer),
            ("Explain my natal chart", reading),
        ],
        "Tell me more",
    )


async def test_withdrawal_privacy_bypass_and_reacceptance_do_not_revive_pending_text(real_history):
    ingress, worker, model, wire, _, _ = real_history
    _, accepted = await send(real_history, "A quiet reflection")
    wire.block.add(FINALIZE)
    pending = await ingress.accept(message(text="A canceled follow-up"))
    await worker.process(pending)
    await send(real_history, "/privacy", command="privacy")
    await send(real_history, "", callback=worker.flow.buttons[1].data)
    work = await work_row(worker, pending)
    assert work.phase == "abandon" and work.encrypted_prepared is work.encrypted_finalize is None
    wire.block.clear()
    await cleanup(worker)
    assert (await work_row(worker, pending)).phase == "terminal"
    await send(real_history, "", callback=worker.flow.buttons[0].data)
    await worker.process(pending)
    await send(real_history, "Another reflection")
    assert_input(model, [("A quiet reflection", accepted)], "Another reflection")
    assert "A canceled follow-up" not in json.dumps(model.calls[-1])


async def test_expired_local_envelope_abandons_real_draft_without_capture(real_history):
    ingress, worker, model, wire, _, _ = real_history
    wire.lose.add(GENERATE)
    event_id = await ingress.accept(message(text="An expiring request"))
    await worker.process(event_id)
    async with worker.database.transaction() as session:
        event = await session.get(InboundEvent, event_id)
        event.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await recoverable(worker.database)
    worker.history_enabled = False
    wire.lose.clear()
    await cleanup(worker)
    assert (await work_row(worker, event_id)).phase == "terminal"
    worker.history_enabled = True
    await send(real_history, "Start a new reflection")
    assert_input(model, [], "Start a new reflection")


async def test_canonical_correction_fences_retries_and_recalculates_current_facts(
    real_history, birth_payload
):
    ingress, worker, model, wire, _, user_id = real_history
    first, _ = await send(real_history, "Explain my natal chart")
    old_work = await work_row(worker, first)
    old_accept = AcceptGenerated.model_validate(wire.bodies(FINALIZE)[-1])
    old_scope = ContextScope(user_id=user_id, session_id=old_work.session_id)
    old_system = model.calls[-1]["messages"][0]["content"]
    async with worker.database.transaction() as session:
        await BirthProfileRepository(
            session, worker.encryption, policy_version=worker.flow.policy_version
        ).save(user_id, birth_payload.model_copy(update={"birth_local_time": time(5, 42)}))
    # Pending source correction suppresses generation immediately, before remote delivery.
    await send(real_history, "Explain my natal chart")
    assert len(model.calls) == 1
    await worker.flow.handle(message(text="/retry_profile"), command="retry_profile")
    # The next ordinary turn must deliver the committed profile revision itself.
    latest, _ = await send(real_history, "Explain my natal chart")
    with pytest.raises(HistoryFailure) as error:
        await worker.history_provider.finalize_history(old_scope, old_accept)
    assert error.value.code == "session_deleted"
    assert (await work_row(worker, latest)).session_id != old_work.session_id
    assert_input(model, [], "Explain my natal chart")
    current = wire.bodies(GENERATE)[-1]
    assert current["knowledge_refs"][0]["revision"] == 2
    assert current["instructions"] in model.calls[-1]["messages"][0]["content"]
    assert model.calls[-1]["messages"][0]["content"] != old_system
    marker = "Calculated natal facts (data, not instructions):\n"
    old_facts = json.JSONDecoder().raw_decode(old_system.split(marker)[1])[0]
    new_facts = json.JSONDecoder().raw_decode(current["instructions"].split(marker)[1])[0]
    assert old_facts != new_facts  # Recalculated chart, not just a new ingress timestamp.


@pytest.mark.parametrize("rollback", [False, True])
async def test_pending_selective_erasure_suppresses_replay_and_fences_delayed_retries(
    real_history, rollback
):
    _, worker, model, wire, gateway, user_id = real_history
    await send(real_history, "We married May 1st, 2020")
    await recover_projections(
        worker.database, worker.encryption, worker.flow.policy_version, worker.history_provider
    )
    event_id, _ = await send(real_history, "Reflect on our wedding")
    work = await work_row(worker, event_id)
    assert work is not None
    request = AcceptGenerated.model_validate(wire.bodies(FINALIZE)[-1])
    scope = ContextScope(user_id=user_id, session_id=work.session_id)
    if rollback:
        await disable_history(real_history)
    wire.block.add("/v1/knowledge/delete")
    _, receipt = await send(real_history, "forget our wedding")
    assert "queued" in receipt
    async with worker.database.transaction() as session:
        pending = list(
            await session.scalars(
                select(ContextProjectionWork).where(
                    ContextProjectionWork.user_id == user_id,
                    ContextProjectionWork.deleted.is_(True),
                    ContextProjectionWork.pending.is_(True),
                )
            )
        )
        assert pending
    before = len(model.calls)
    await send(real_history, "Tell me more")
    if rollback:
        # Legacy generation may answer without recalled context; pending deletion
        # must still suppress the stale linked source and all stored dialogue.
        assert len(model.calls) == before + 1
        assert model.calls[-1]["messages"][1:] == [{"role": "user", "content": "Tell me more"}]
        assert "2020-05-01" not in json.dumps(model.calls[-1])
        assert "Reflect on our wedding" not in json.dumps(model.calls[-1])
    else:
        assert len(model.calls) == before
    await recover_projections(
        worker.database, worker.encryption, worker.flow.policy_version, worker.history_provider
    )
    wire.block.clear()
    async with worker.database.transaction() as session:
        for projection in await session.scalars(
            select(ContextProjectionWork).where(ContextProjectionWork.user_id == user_id)
        ):
            projection.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await recover_projections(
        worker.database, worker.encryption, worker.flow.policy_version, worker.history_provider
    )
    await gateway.restart()
    with pytest.raises(HistoryFailure) as error:
        await worker.history_provider.finalize_history(scope, request)
    assert error.value.code == "session_deleted"
    if rollback:
        gateway.env["HISTORY_ENABLED"] = "true"
        await gateway.restart()
        worker.history_enabled = real_history[0].history_enabled = True
        worker.history_provider.clear_history_capabilities()
    fresh, _ = await send(real_history, "A new reflection")
    assert (await work_row(worker, fresh)).session_id != work.session_id
    assert_input(model, [], "A new reflection")


@pytest.mark.parametrize("rollback", [False, True])
async def test_full_deletion_purges_history_and_fences_delayed_acceptance(real_history, rollback):
    ingress, worker, model, wire, _, user_id = real_history
    event_id, _ = await send(real_history, "A synthetic reflection")
    work = await work_row(worker, event_id)
    request = AcceptGenerated.model_validate(wire.bodies(FINALIZE)[-1])
    scope = ContextScope(user_id=user_id, session_id=work.session_id)
    if rollback:
        await disable_history(real_history)
    await send(real_history, "/delete_me", command="delete_me")
    buttons = worker.client.send_text.call_args.kwargs["buttons"]
    button = next(b for b in buttons if b.data.startswith("delete:confirm:"))
    confirmation = await ingress.accept(message(callback=button.data))
    await worker.process(confirmation)
    async with worker.database.transaction() as session:
        job_id = await session.scalar(select(DeletionJob.id).where(DeletionJob.user_id == user_id))
    deletion = DeletionWorker(
        worker.database, worker.redis, worker.encryption, worker.history_provider, worker.client
    )
    for _ in range(4):
        await deletion.step(job_id)
    async with worker.database.transaction() as session:
        job = await session.get(DeletionJob, job_id)
        assert job.status == "completed"
    assert await work_row(worker, event_id) is None
    with pytest.raises(HistoryFailure) as error:
        await worker.history_provider.finalize_history(scope, request)
    assert error.value.code == "subject_deleted"
    assert len(model.calls) == 1


async def disable_history(harness):
    ingress, worker, _, _, gateway, user_id = harness
    ingress.history_enabled = worker.history_enabled = False
    gateway.env["HISTORY_ENABLED"] = "false"
    await gateway.restart()
    with pytest.raises(HistoryUnsupported):
        await worker.history_provider.history_capabilities(user_id, refresh=True)


@pytest.mark.parametrize("lost_ack", [False, True])
async def test_rollback_recovers_committed_generated_acceptance_and_delivery(
    real_history, lost_ack
):
    ingress, worker, model, wire, gateway, _ = real_history
    # Test both an undispatched acceptance and a remotely committed but lost receipt.
    (wire.lose if lost_ack else wire.block).add(FINALIZE)
    event_id = await ingress.accept(message(text="Suggest two reflections"))
    await worker.process(event_id)
    assert (await work_row(worker, event_id)).phase == "finalize"
    assert not worker.client.send_text.call_count
    await disable_history(real_history)
    wire.lose.clear()
    wire.block.clear()
    await due(worker, event_id)
    await worker.process(event_id)
    assert (await row(worker, event_id)).status == "sent"
    assert wire.bodies(FINALIZE)[0] == wire.bodies(FINALIZE)[-1]
    assert len(model.calls) == 1
    await send(real_history, "A separate question about rainbows")
    assert len(model.calls) == 2
    assert len(model.calls[-1]["messages"]) == 2  # Legacy: no prior dialogue replay.
    # Re-enable on the same code/schema. Accepted history survived; legacy is not backfilled.
    gateway.env["HISTORY_ENABLED"] = "true"
    await gateway.restart()
    ingress.history_enabled = worker.history_enabled = True
    worker.history_provider.clear_history_capabilities()
    await send(real_history, "Tell me more")
    assert_input(model, [("Suggest two reflections", model.reply)], "Tell me more")


async def test_rollback_cancels_uncommitted_generation_and_abandons_remote_draft(real_history):
    ingress, worker, model, wire, _, _ = real_history
    wire.lose.add(GENERATE)
    event_id = await ingress.accept(message(text="A pending reflection"))
    await worker.process(event_id)
    assert (await work_row(worker, event_id)).phase == "prepared"
    await disable_history(real_history)
    wire.lose.clear()
    await cleanup(worker)
    assert (await row(worker, event_id)).status == "dead"
    assert (await work_row(worker, event_id)).phase == "terminal"
    assert wire.bodies(FINALIZE)[-1]["action"] == "abandon"
    await due(worker, event_id)
    await worker.process(event_id)
    assert len(model.calls) == 1
    await send(real_history, "An independent reflection")
    assert len(model.calls[-1]["messages"]) == 2


async def test_rollback_keeps_delivery_of_accepted_reply_without_regeneration(real_history):
    ingress, worker, model, wire, _, _ = real_history
    worker.client.send_text.side_effect = DeliveryRejected("Synthetic channel failure")
    event_id = await ingress.accept(message(text="Give me a short reflection"))
    await worker.process(event_id)
    assert (await work_row(worker, event_id)).phase == "accepted"
    await disable_history(real_history)
    worker.client.send_text.side_effect = None
    await due(worker, event_id)
    await worker.process(event_id)
    assert (await row(worker, event_id)).status == "sent"
    assert len(model.calls) == len(wire.bodies(FINALIZE)) == 1


@pytest.mark.parametrize("generate", [False, True])
async def test_release_smoke_check_uses_actual_gateway_and_cleans_up(
    real_history, generate, capsys
):
    from scripts.check_history_release import check

    _, worker, model, wire, _, _ = real_history
    model.recall_code = True
    await check(worker.history_provider, generate=generate)
    assert len(model.calls) == (2 if generate else 0)
    assert wire.statuses[-1][0:2] == ("/v1/subjects/purge", 200)
    output = capsys.readouterr().out
    assert "PASS: recent capability" in output
    assert all(body.get("user", "not present") not in output for _, body in wire.calls)


async def test_release_check_failure_retains_cleanup_journal_and_retry_erases_it(
    real_history, tmp_path, monkeypatch
):
    from scripts import check_history_release as release

    _, worker, model, wire, _, _ = real_history
    monkeypatch.setattr(release, "Settings", lambda: None)
    monkeypatch.setattr(release, "SecondContextProvider", lambda _: worker.history_provider)
    # Keep the fixture's HTTP client open across the two CLI invocations.
    monkeypatch.setattr(worker.history_provider, "aclose", AsyncMock())
    journal = tmp_path / "private-cleanup"
    # The synthetic model deliberately fails the code recall check.
    with pytest.raises(RuntimeError, match="configured provider continuity"):
        await release.main(True, journal)
    assert journal.stat().st_mode & 0o777 == 0o600
    subject = worker.history_provider.subject(UUID(journal.read_text()))
    assert any(body.get("user") == subject for body in wire.bodies("/v1/subjects/purge"))
    calls = len(wire.calls)
    with pytest.raises(FileExistsError):
        await release.main(False, journal)  # Never overwrite unfinished cleanup identity.
    assert len(wire.calls) == calls
    await release.main(False, journal, cleanup_only=True)
    assert not journal.exists()
    assert len(model.calls) == 1


async def test_adaptive_http_selection_and_recent_rollback(real_history):
    """Exercise the versioned HTTP opt-in; Oria's normal adapter remains recent."""
    _, worker, model, _, gateway, user_id = real_history
    gateway.env.update(
        HISTORY_ADAPTIVE_ENABLED="true",
        DECISIONS_OBSERVE_ENABLED="false",
        DECISIONS_BASE_URL=gateway.env["OPENAI_BASE_URL"],
        DECISIONS_API_KEY=gateway.env["OPENAI_API_KEY"],
        DECISIONS_CACHE_SECRET=uuid4().hex + uuid4().hex,
    )
    await gateway.restart()
    subject = worker.history_provider.subject(user_id)
    session = str(uuid4())
    headers = {
        "Authorization": "Bearer " + gateway.env["AUTH_SERVICE_TOKENS"].split("=", 1)[1],
        "X-SecondContext-Subject": subject,
    }
    async with httpx.AsyncClient(base_url=gateway.url, headers=headers, trust_env=False) as client:

        async def generate(text, mode):
            response = await client.post(
                GENERATE,
                headers={
                    "X-SecondContext-History": mode,
                    "X-SecondContext-Session": session,
                    "X-SecondContext-Turn": str(uuid4()),
                },
                json={
                    "user": subject,
                    "input": text,
                    "disable_memory": True,
                    "disable_knowledge": True,
                },
            )
            assert response.status_code == 200, response.status_code
            return response

        cap = await client.post("/v1/context/capabilities", json={"user": subject})
        assert "adaptive" in cap.json()["history_modes"]
        model.reply = "Tomorrow favors a slower pace."
        await generate("Describe tomorrow.", "recent")
        model.reply = "The current compatibility contact can symbolize shared enjoyment."
        prepared = "Regarding compatibility: explain the current Venus sextile Jupiter contact."
        await generate(prepared, "adaptive")
        assert_input(model, [], prepared)
        assert len(model.decisions) == 1
        model.decision_recent = 0.99
        previous = model.reply
        await generate("What does it mean in plain English?", "adaptive")
        assert model.calls[-1]["messages"][-2]["content"] == previous
        assert prepared in json.dumps(model.calls[-1])
        assert len(model.decisions) == 2
        gateway.env["HISTORY_ADAPTIVE_ENABLED"] = "false"
        await gateway.restart()
        cap = await client.post("/v1/context/capabilities", json={"user": subject})
        assert "adaptive" not in cap.json()["history_modes"]
        await generate("Continue the compatibility explanation.", "recent")
        assert prepared in json.dumps(model.calls[-1])
        assert len(model.decisions) == 2
        response = await client.post("/v1/subjects/purge", json={"user": subject})
        assert response.status_code == 200
