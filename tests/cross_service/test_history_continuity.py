"""Synthetic dialogue through Oria workers and the real SecondContext HTTP gateway."""

import asyncio
import json
from datetime import UTC, datetime, time, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from oria_engine.context.contracts import ContextReply, ContextScope, ConversationRequest
from oria_engine.context.history import AcceptGenerated, HistoryFailure
from oria_engine.context.history_workflow import capture_local
from oria_engine.context.projections import LinkedContext, recover_projections
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
    async with worker.database.transaction() as session:
        linked = LinkedContext(
            session, worker.encryption, worker.flow.policy_version, worker.history_provider
        )
        await linked.stage(user_id)
        for projection in await linked.repo.rows(user_id):
            projection.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await recover_projections(
        worker.database, worker.encryption, worker.flow.policy_version, worker.history_provider
    )
    with pytest.raises(HistoryFailure) as error:
        await worker.history_provider.finalize_history(old_scope, old_accept)
    assert error.value.code == "session_deleted"
    latest, _ = await send(real_history, "Explain my natal chart")
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


async def test_pending_selective_erasure_suppresses_replay_and_fences_delayed_retries(real_history):
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
    fresh, _ = await send(real_history, "A new reflection")
    assert (await work_row(worker, fresh)).session_id != work.session_id
    assert_input(model, [], "A new reflection")


async def test_full_deletion_purges_history_and_fences_delayed_acceptance(real_history):
    ingress, worker, model, wire, _, user_id = real_history
    event_id, _ = await send(real_history, "A synthetic reflection")
    work = await work_row(worker, event_id)
    request = AcceptGenerated.model_validate(wire.bodies(FINALIZE)[-1])
    scope = ContextScope(user_id=user_id, session_id=work.session_id)
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
