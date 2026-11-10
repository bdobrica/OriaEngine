"""Synthetic HTTP plus real transactions/queue: durable consumer lifecycle, not model quality."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from oria_engine.context.history_recovery import recover_history
from oria_engine.context.projections import LinkedContext, recover_projections
from oria_engine.context.service import ConversationContext
from oria_engine.db.models import ConversationHistoryWork, InboundEvent
from oria_engine.domain.channel import DeliveryRejected
from oria_engine.domain.policy import PRIVACY_REPLY
from oria_engine.privacy.encryption import ProfileEncryptionError
from oria_engine.queue.events import EventWorker, recoverable
from tests.contract.test_history_adapter import example

from .test_astrology_profiles import confirm
from .test_conversation_worker import conversation as conversation
from .test_projections import ProjectionService, provider
from .test_queue import due, message, row
from .test_queue import queue as queue


class HistoryService(ProjectionService):
    def __init__(self):
        super().__init__()
        self.turns = {}
        self.generated = []
        self.finalized = []
        self.text = "The second option gives you more room to reflect."
        self.lose_generation = False
        self.lose_receipt = False
        self.fail_finalize = False
        self.bad_receipt = False

    def __call__(self, request):
        body = json.loads(request.content)
        if request.url.path == "/v1/context/capabilities":
            value = example("baseline")
            value["user"] = body["user"]
            return httpx.Response(200, json=value)
        if request.url.path == "/v1/responses":
            assert request.headers["X-SecondContext-History"] == "recent"
            assert request.headers["X-SecondContext-Acceptance"] == "explicit"
            key = (
                body["user"],
                request.headers["X-SecondContext-Session"],
                request.headers["X-SecondContext-Turn"],
            )
            self.generated.append(body)
            old = self.turns.setdefault(
                key, {"body": body, "text": self.text, "sequence": len(self.turns) + 1}
            )
            assert old["body"] == body
            if self.lose_generation:
                raise httpx.ReadTimeout("synthetic")
            return httpx.Response(
                200,
                json={
                    "id": "resp_" + key[2],
                    "object": "response",
                    "status": "completed",
                    "output_text": old["text"],
                    "metadata": {
                        "session_id": key[1],
                        "context_packet": {"user_external_id": key[0]},
                    },
                },
                headers={
                    "X-SecondContext-Contract": "conversation-history-1",
                    "X-SecondContext-Session": key[1],
                    "X-SecondContext-Turn": key[2],
                    "X-SecondContext-Snapshot": "0",
                },
            )
        if request.url.path == "/v1/context/turns/finalize":
            self.finalized.append(body)
            if self.fail_finalize:
                return httpx.Response(503, json={"error": {"code": "history_unavailable"}})
            key = (body["user"], body["session_id"], body["turn_id"])
            old = self.turns.setdefault(key, {"sequence": len(self.turns) + 1})
            if body["action"] == "abandon" and old.get("accepted"):
                return httpx.Response(409, json={"error": {"code": "turn_conflict"}})
            if "finalize" in old:
                assert old["finalize"] == body
            old["finalize"] = body
            old["accepted"] = body["action"] != "abandon"
            receipt = {
                name: body[name]
                for name in ("contract_version", "user", "session_id", "turn_id", "action")
            }
            receipt.update(
                sequence=old["sequence"],
                history_coverage="linked_sessions",
                status="accepted" if old["accepted"] else "abandoned",
            )
            if "response_id" in body:
                receipt["response_id"] = body["response_id"]
            if self.lose_receipt:
                raise httpx.ReadTimeout("synthetic")
            if self.bad_receipt:
                receipt["turn_id"] = str(uuid4())
            return httpx.Response(200, json=receipt)
        return super().__call__(request)


@pytest.fixture
async def managed(conversation, request):
    ingress, worker, astrology, _ = conversation
    remote = HistoryService()
    p = provider(remote)
    worker.flow.onboarding.context = ConversationContext(p, worker.flow.policy_version)
    worker.history_provider, worker.history_enabled = p, True
    ingress.history_enabled = True
    await confirm(worker.flow)
    from .test_onboarding import owner

    user_id = await owner(worker.database)
    # Seed acknowledged current canonical sources through the public HTTP projection lane.
    if getattr(request, "param", None) != "unprojected":
        async with worker.database.transaction() as session:
            linked = LinkedContext(session, worker.encryption, worker.flow.policy_version, p)
            await linked.stage(user_id)
        await recover_projections(worker.database, worker.encryption, worker.flow.policy_version, p)
    try:
        yield ingress, worker, remote, user_id
    finally:
        await p.aclose()


async def work_row(worker, event_id):
    async with worker.database.transaction() as session:
        return await session.get(ConversationHistoryWork, event_id)


@pytest.mark.parametrize("managed", ["unprojected"], indirect=True)
async def test_first_reading_projects_committed_profile_before_generation(managed):
    ingress, worker, remote, user_id = managed
    from oria_engine.db.models import ContextProjectionWork

    original = worker.history_provider.project

    async def project(request):
        async with worker.database.transaction() as session:
            rows = (await session.scalars(select(ContextProjectionWork))).all()
            assert rows and all(row.pending for row in rows)
        assert not remote.generated
        return await original(request)

    event_id = await ingress.accept(message(text="How is my day going today?"))
    with patch.object(worker.history_provider, "project", side_effect=project):
        await worker.process(event_id)
    assert (await row(worker, event_id)).status == "sent"
    assert len(remote.generated) == 1
    assert remote.generated[0]["knowledge_refs"]
    assert (await work_row(worker, event_id)).receipt
    assert worker.client.send_text.call_args.args[1] == remote.text


@pytest.mark.parametrize("managed", ["unprojected"], indirect=True)
async def test_first_reading_keeps_local_fallback_when_projection_unavailable(managed):
    ingress, worker, remote, _ = managed
    remote.fail = True
    event_id = await ingress.accept(message(text="today"))
    await worker.process(event_id)
    assert (await row(worker, event_id)).status == "sent"
    assert not remote.generated
    assert await work_row(worker, event_id) is None
    assert "Transit snapshot:" in worker.client.send_text.call_args.args[1]
    remote.fail = False
    from oria_engine.db.models import ContextProjectionWork

    async with worker.database.transaction() as session:
        for projection in await session.scalars(select(ContextProjectionWork)):
            projection.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    event_id = await ingress.accept(message(text="today"))
    await worker.process(event_id)
    assert (await row(worker, event_id)).status == "sent"
    assert len(remote.generated) == 1


async def cleanup(worker):
    await recover_history(
        worker.database,
        worker.encryption,
        worker.flow.policy_version,
        worker.history_provider,
        enabled=worker.history_enabled,
    )


async def test_preparation_commits_before_http_and_reply_before_finalize(managed):
    ingress, worker, remote, user_id = managed
    event_id = await ingress.accept(message(text="Which option works?"))
    original_generate = worker.history_provider.respond_history
    original_finalize = worker.history_provider.finalize_history

    async def generate(scope, prepared):
        work = await work_row(worker, event_id)
        assert work.phase == "prepared" and work.encrypted_prepared
        # Cancellation IDs outlive the provider TTL even if HTTP starts at the
        # end of the bounded worker attempt; sensitive event retention is unchanged.
        assert work.cleanup_until > datetime.now(UTC) + timedelta(hours=24)
        assert b"Which option" not in work.encrypted_prepared
        assert prepared.turn_id == event_id
        assert (await row(worker, event_id)).encrypted_reply is None
        return await original_generate(scope, prepared)

    async def finalize(scope, request):
        work = await work_row(worker, event_id)
        event = await row(worker, event_id)
        assert work.phase == "finalize" and work.accept_attempted
        assert event.encrypted_reply and work.encrypted_finalize
        worker.client.send_text.assert_not_called()
        return await original_finalize(scope, request)

    with (
        patch.object(worker.history_provider, "respond_history", side_effect=generate),
        patch.object(worker.history_provider, "finalize_history", side_effect=finalize),
    ):
        await worker.process(event_id)
    work = await work_row(worker, event_id)
    assert (await row(worker, event_id)).status == "sent"
    assert work.phase == "terminal" and work.delivery == "sent" and work.receipt
    assert work.encrypted_prepared is work.encrypted_finalize is None
    assert remote.finalized[0]["assistant_text"] == worker.client.send_text.call_args.args[1]
    assert remote.generated[0]["knowledge_refs"]


async def test_lost_generation_reuses_encrypted_body_after_restart(managed):
    ingress, worker, remote, _ = managed
    remote.lose_generation = True
    event_id = await ingress.accept(message(text="today"))
    await worker.process(event_id)
    assert (await work_row(worker, event_id)).phase == "prepared"
    remote.lose_generation = False
    await due(worker, event_id)
    restarted = EventWorker(
        worker.database,
        worker.redis,
        worker.encryption,
        worker.flow,
        worker.client,
        history_provider=worker.history_provider,
        history_enabled=True,
    )
    await restarted.process(event_id)
    assert remote.generated[0] == remote.generated[1]
    assert len(remote.turns) == 1
    assert (await row(worker, event_id)).status == "sent"


@pytest.mark.parametrize("failure", ["lose_receipt", "bad_receipt"])
async def test_acceptance_ack_failure_retries_exact_body_without_generation(managed, failure):
    ingress, worker, remote, _ = managed
    setattr(remote, failure, True)
    event_id = await ingress.accept(message(text="Tell me more"))
    await worker.process(event_id)
    work = await work_row(worker, event_id)
    assert work.phase == "finalize" and work.accept_attempted and not work.receipt
    worker.client.send_text.assert_not_called()
    setattr(remote, failure, False)
    await due(worker, event_id)
    await worker.process(event_id)
    assert len(remote.generated) == 1 and remote.finalized[0] == remote.finalized[1]
    assert (await row(worker, event_id)).status == "sent"


async def test_replaced_draft_and_final_snapshot_are_accepted_exactly(managed):
    ingress, worker, remote, _ = managed
    remote.text = "Tell me your email."
    event_id = await ingress.accept(message(text="Tell me more"))
    await worker.process(event_id)
    assert remote.finalized[0]["assistant_text"] == PRIVACY_REPLY
    assert worker.client.send_text.call_args.args[1] == PRIVACY_REPLY
    assert remote.turns[next(iter(remote.turns))]["text"] != PRIVACY_REPLY


@pytest.mark.parametrize(
    "error,delivery",
    [(DeliveryRejected("synthetic"), "failed"), (RuntimeError("synthetic"), "unknown")],
)
async def test_delivery_is_independent_and_later_generation_waits(managed, error, delivery):
    ingress, worker, remote, _ = managed
    first = await ingress.accept(message(text="Tell me more"))
    second = await ingress.accept(message(text="Which one?"))
    worker.client.send_text.side_effect = error
    await worker.process(first)
    assert (await work_row(worker, first)).delivery == delivery
    await worker.process(second)
    assert len(remote.generated) == 1
    worker.client.send_text.side_effect = None
    await due(worker, first)
    await worker.process(first)
    await worker.process(second)
    assert len(remote.generated) == 2 and len(remote.finalized) == 2


async def test_terminal_delivery_marks_next_prompt_unconfirmed(managed):
    ingress, worker, remote, _ = managed
    worker.client.send_text.side_effect = RuntimeError("synthetic")
    first = await ingress.accept(message(text="Tell me more"))
    for _ in range(5):
        await due(worker, first)
        await worker.process(first)
    assert (await row(worker, first)).status == "dead"
    work = await work_row(worker, first)
    assert work.receipt and work.encrypted_prepared is None and work.delivery == "unknown"
    worker.client.send_text.side_effect = None
    await worker.process(await ingress.accept(message(text="Which one?")))
    assert "unconfirmed channel delivery" in remote.generated[-1]["instructions"]
    assert len(remote.generated) == 2


async def test_privacy_bypass_withdrawal_and_reacceptance_cannot_revive(managed):
    ingress, worker, remote, _ = managed
    remote.fail_finalize = True
    first = await ingress.accept(message(text="Tell me more"))
    await worker.process(first)
    privacy = await ingress.accept(message(text="/privacy"), command="privacy")
    assert await ingress.publishable(privacy)
    assert privacy in await recoverable(worker.database)
    await worker.process(privacy)
    assert (await row(worker, privacy)).status == "sent"
    decline = await ingress.accept(message(callback=worker.flow.buttons[1].data))
    await worker.process(decline)
    assert (await row(worker, first)).status == "dead"
    work = await work_row(worker, first)
    assert work.phase == "abandon" and not work.encrypted_finalize and not work.encrypted_prepared
    remote.fail_finalize = False
    await cleanup(worker)
    assert remote.finalized[-1]["action"] == "abandon"
    await worker.process(await ingress.accept(message(callback=worker.flow.buttons[0].data)))
    await due(worker, first)
    await worker.process(first)
    assert len(remote.generated) == 1


async def test_expiry_wipes_work_then_abandons_without_capture_enablement(managed):
    ingress, worker, remote, _ = managed
    remote.lose_generation = True
    event_id = await ingress.accept(message(text="Tell me more"))
    await worker.process(event_id)
    async with worker.database.transaction() as session:
        event = await session.get(InboundEvent, event_id)
        event.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await recoverable(worker.database)
    work = await work_row(worker, event_id)
    assert work.phase == "abandon" and work.encrypted_prepared is None
    worker.history_enabled = False
    await cleanup(worker)
    assert (await work_row(worker, event_id)).phase == "terminal"
    assert remote.finalized[-1]["action"] == "abandon"


@pytest.mark.parametrize(
    "text,command",
    [
        ("My password is synthetic-secret", None),
        ("/profile", "profile"),
        ("/privacy", "privacy"),
        ("/help", "help"),
        ("transits tomorrow", None),
        ("My girlfriend Alice was born June 2nd, 1992", None),
        ("forget my girlfriend", None),
    ],
)
async def test_excluded_exchanges_are_not_captured(managed, text, command):
    ingress, worker, remote, _ = managed
    event_id = await ingress.accept(message(text=text), command=command)
    await worker.process(event_id)
    assert (await row(worker, event_id)).status == "sent"
    assert not remote.generated and not remote.finalized
    assert await work_row(worker, event_id) is None


async def test_local_calculated_exchange_uses_same_acceptance_lane(managed):
    ingress, worker, remote, _ = managed
    worker.flow.onboarding.context = None  # Supported deterministic consumer.
    event_id = await ingress.accept(message(text="Explain my natal chart"))
    await worker.process(event_id)
    assert not remote.generated and remote.finalized[0]["action"] == "accept_local"
    assert remote.finalized[0]["knowledge_refs"]
    assert remote.finalized[0]["assistant_text"] == worker.client.send_text.call_args.args[1]


async def test_pending_sources_leave_local_reading_uncaptured(managed):
    from oria_engine.db.models import ContextProjectionWork

    ingress, worker, remote, user_id = managed
    async with worker.database.transaction() as session:
        for projection in await session.scalars(
            select(ContextProjectionWork).where(ContextProjectionWork.user_id == user_id)
        ):
            projection.pending = True
            projection.next_attempt_at = datetime.now(UTC) + timedelta(minutes=5)
    event_id = await ingress.accept(message(text="Explain my natal chart"))
    await worker.process(event_id)
    assert (await row(worker, event_id)).status == "sent"
    assert not remote.generated and not remote.finalized
    assert "Your saved natal chart" in worker.client.send_text.call_args.args[1]
    assert "not a scientific forecast" not in worker.client.send_text.call_args.args[1]


async def test_precommit_failure_keeps_only_prepared_work_and_retries(managed):
    from oria_engine.db.history import HistoryRepository

    ingress, worker, remote, _ = managed
    event_id = await ingress.accept(message(text="Tell me more"))
    with patch.object(HistoryRepository, "stage", side_effect=RuntimeError("synthetic rollback")):
        await worker.process(event_id)
    event = await row(worker, event_id)
    assert event.encrypted_input and event.encrypted_reply is None
    assert (await work_row(worker, event_id)).phase == "prepared"
    assert not remote.finalized
    worker.client.send_text.assert_not_called()
    await due(worker, event_id)
    await worker.process(event_id)
    assert (await row(worker, event_id)).status == "sent"
    assert remote.generated[0] == remote.generated[1] and len(remote.turns) == 1


async def test_profile_revision_cancels_prepared_work_then_rotates_after_cleanup(
    managed, birth_payload
):
    from oria_engine.db.birth_profiles import BirthProfileRepository

    ingress, worker, remote, user_id = managed
    remote.lose_generation = True
    event_id = await ingress.accept(message(text="Tell me more"))
    await worker.process(event_id)
    old_session = (await work_row(worker, event_id)).session_id
    async with worker.database.transaction() as session:
        await BirthProfileRepository(
            session, worker.encryption, policy_version=worker.flow.policy_version
        ).save(user_id, birth_payload)
    work = await work_row(worker, event_id)
    assert work.phase == "abandon" and not work.encrypted_prepared
    assert (await row(worker, event_id)).status == "dead"
    await cleanup(worker)
    remote.lose_generation = False
    # Recalculate current canonical facts and acknowledge source revision before new capture.
    await worker.flow.handle(message(text="/retry_profile"), command="retry_profile")
    async with worker.database.transaction() as session:
        linked = LinkedContext(
            session, worker.encryption, worker.flow.policy_version, worker.history_provider
        )
        await linked.stage(user_id)
    await recover_projections(
        worker.database, worker.encryption, worker.flow.policy_version, worker.history_provider
    )
    second = await ingress.accept(message(text="Explain my chart"))
    await worker.process(second)
    assert (await row(worker, second)).status == "sent"
    assert (await work_row(worker, second)).session_id != old_session
    assert remote.generated[-1]["knowledge_refs"][0]["revision"] == 2


async def test_disable_capture_preserves_committed_finalization_and_delivery(managed):
    ingress, worker, remote, _ = managed
    remote.lose_receipt = True
    event_id = await ingress.accept(message(text="Tell me more"))
    await worker.process(event_id)
    worker.history_enabled = False
    remote.lose_receipt = False
    await due(worker, event_id)
    await worker.process(event_id)
    assert (await row(worker, event_id)).status == "sent"
    assert len(remote.generated) == 1 and remote.finalized[0] == remote.finalized[1]


async def test_disable_capture_cancels_prepared_generation(managed):
    ingress, worker, remote, _ = managed
    remote.lose_generation = True
    event_id = await ingress.accept(message(text="Tell me more"))
    await worker.process(event_id)
    worker.history_enabled = False
    remote.lose_generation = False
    await cleanup(worker)
    assert (await row(worker, event_id)).status == "dead"
    assert (await work_row(worker, event_id)).phase == "terminal"
    await due(worker, event_id)
    await worker.process(event_id)
    assert len(remote.generated) == 1


async def test_ambiguous_acceptance_exhaustion_keeps_no_text_and_does_not_claim_abandoned(managed):
    ingress, worker, remote, _ = managed
    remote.lose_receipt = True
    event_id = await ingress.accept(message(text="Tell me more"))
    for _ in range(5):
        await due(worker, event_id)
        await worker.process(event_id)
    work = await work_row(worker, event_id)
    assert work.phase == "abandon" and work.accept_attempted
    assert not work.receipt and work.encrypted_finalize is work.encrypted_prepared is None
    remote.lose_receipt = False
    await cleanup(worker)  # Remote acceptance cannot be abandoned.
    assert (await work_row(worker, event_id)).phase == "abandon"
    async with worker.database.transaction() as session:
        work = await session.get(ConversationHistoryWork, event_id)
        work.cleanup_until = datetime.now(UTC) - timedelta(seconds=1)
    await cleanup(worker)
    assert (await work_row(worker, event_id)).phase == "terminal"
    assert len(remote.generated) == 1
    worker.client.send_text.assert_not_called()


async def test_account_deletion_cancels_history_before_purge(managed):
    ingress, worker, remote, _ = managed
    remote.fail_finalize = True
    event_id = await ingress.accept(message(text="Tell me more"))
    await worker.process(event_id)
    request = await ingress.accept(message(text="/delete_me"), command="delete_me")
    await worker.process(request)
    buttons = worker.client.send_text.call_args.kwargs["buttons"]
    confirm_button = next(button for button in buttons if button.data.startswith("delete:confirm:"))
    deletion = await ingress.accept(message(callback=confirm_button.data))
    await worker.process(deletion)
    assert (await row(worker, event_id)).status == "dead"
    work = await work_row(worker, event_id)
    assert not work.encrypted_prepared and not work.encrypted_finalize
    before = len(remote.finalized)
    await cleanup(worker)
    assert len(remote.finalized) == before  # Full-subject purge owns the fenced account.
    from oria_engine.db.models import DeletionJob
    from oria_engine.privacy.deletion import DeletionWorker

    async with worker.database.transaction() as session:
        job_id = await session.scalar(
            select(DeletionJob.id).where(DeletionJob.user_id == work.user_id)
        )
    deletion_worker = DeletionWorker(
        worker.database, worker.redis, worker.encryption, worker.history_provider, worker.client
    )
    await deletion_worker.step(job_id)
    assert await work_row(worker, event_id) is None
    assert (await row(worker, event_id)).encrypted_input is None


async def test_current_input_and_finalize_ciphertexts_are_bound_to_owner_event_and_kind(managed):
    from oria_engine.db.history import HistoryRepository

    ingress, worker, remote, _ = managed
    remote.fail_finalize = True
    event_id = await ingress.accept(message(text="Tell me more"))
    await worker.process(event_id)
    work = await work_row(worker, event_id)
    async with worker.database.transaction() as session:
        repo = HistoryRepository(session, worker.encryption, worker.flow.policy_version)
        assert repo.prepared(work).input == "Tell me more"
        assert repo.finalization(work).assistant_text == remote.text
        with pytest.raises(ProfileEncryptionError):
            repo.decrypt(work, work.encrypted_prepared, "finalize")
        work.event_id = uuid4()
        with pytest.raises(ProfileEncryptionError):
            repo.prepared(work)


async def test_withdrawal_wipes_unattempted_managed_inputs_and_never_revives(managed):
    ingress, worker, remote, user_id = managed
    from oria_engine.db.repositories import ConsentRepository

    event_id = await ingress.accept(message(text="Tell me more"))
    async with worker.database.transaction() as session:
        await ConsentRepository(session).revoke(user_id, "telegram")
        await ConsentRepository(session).accept(user_id, worker.flow.policy_version, "telegram")
    event = await row(worker, event_id)
    assert event.status == "dead" and event.encrypted_input is None
    worker.history_enabled = False
    await worker.process(event_id)
    assert not remote.generated and not remote.finalized


async def test_known_rejection_does_not_clear_previous_ambiguous_delivery(managed):
    ingress, worker, _, _ = managed
    event_id = await ingress.accept(message(text="Tell me more"))
    worker.client.send_text.side_effect = RuntimeError("synthetic lost send acknowledgement")
    await worker.process(event_id)
    worker.client.send_text.side_effect = DeliveryRejected("synthetic rejection")
    await due(worker, event_id)
    await worker.process(event_id)
    assert (await work_row(worker, event_id)).delivery == "unknown"


@pytest.mark.parametrize(
    "action,is_control",
    [(None, False), ("learn", False), ("correct", False), ("read", True), ("delete", True)],
)
async def test_focus_alone_does_not_promote_followup_to_privacy_bypass(managed, action, is_control):
    from oria_engine.db.knowledge import KnowledgeRepository, MemoryProgress
    from oria_engine.db.repositories import ConsentRepository

    ingress, worker, _, user_id = managed
    async with worker.database.transaction() as session:
        consent = await ConsentRepository(session).current(user_id, worker.flow.policy_version)
        await KnowledgeRepository(
            session, worker.encryption, worker.flow.policy_version
        ).set_progress(
            user_id,
            MemoryProgress(
                consent_id=consent.id, reference_time_utc=datetime.now(UTC), action=action
            ),
        )
    event_id = await ingress.accept(message(text="yes"))
    assert (await row(worker, event_id)).is_control is is_control
