"""Real PostgreSQL/Redis, synthetic Telegram and the versioned context HTTP boundary."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from redis.exceptions import ConnectionError
from sqlalchemy import delete, select

from oria_engine.config import Settings
from oria_engine.context.contracts import ContextScope, ContextUnavailable, ConversationRequest
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.context.service import ConversationContext
from oria_engine.db.models import (
    AstrologyProfile,
    BirthProfile,
    Consent,
    ConversationSession,
    DeletionJob,
    InboundEvent,
    OnboardingProgress,
    SocialIdentity,
    User,
)
from oria_engine.db.repositories import UserUnavailableError
from oria_engine.privacy.deletion import FINAL_TEXT, DeletionWorker
from tests.support.second_context import SecondContextStub

from .conftest import migrate
from .test_astrology_profiles import confirm
from .test_conversation_worker import conversation as conversation
from .test_queue import message, row
from .test_queue import queue as queue


@pytest.fixture
async def deletion(conversation):
    ingress, worker, _, _ = conversation
    stub = SecondContextStub(namespace="oria", token="synthetic-test-token")
    context = SecondContextProvider(
        Settings(
            _env_file=None,
            second_context_subject_namespace="oria",
            second_context_bearer_token="synthetic-test-token",
        ),
        transport=httpx.MockTransport(stub),
    )
    worker.flow.onboarding.context = ConversationContext(context, worker.flow.policy_version)
    runner = DeletionWorker(
        worker.database, worker.redis, worker.encryption, context, worker.client
    )
    try:
        yield ingress, worker, runner, stub
    finally:
        await context.aclose()
        async with worker.database.transaction() as session:
            await session.execute(delete(DeletionJob))


async def send(ingress, worker, *, command=None, callback=None, user="42"):
    inbound = message(user=user, callback=callback)
    identifier = await ingress.accept(inbound, command=command)
    await worker.process(identifier)
    return inbound, identifier


async def job_for(worker, user_id):
    async with worker.database.transaction() as session:
        return await session.scalar(select(DeletionJob).where(DeletionJob.user_id == user_id))


async def request(ingress, worker):
    _, event_id = await send(ingress, worker, command="delete-me")
    user_id = (await row(worker, event_id)).user_id
    buttons = worker.client.send_text.call_args.kwargs["buttons"]
    inbound, confirmation = await send(ingress, worker, callback=buttons[0].data)
    return user_id, (await job_for(worker, user_id)).id, inbound, confirmation


async def make_due(worker, identifier):
    async with worker.database.transaction() as session:
        job = await session.get(DeletionJob, identifier)
        job.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)


async def assert_local_erased(worker, user_id, *, completed):
    async with worker.database.transaction() as session:
        for model in (
            BirthProfile,
            AstrologyProfile,
            OnboardingProgress,
            ConversationSession,
            Consent,
        ):
            assert await session.scalar(select(model).where(model.user_id == user_id)) is None
        user = await session.get(User, user_id)
        if completed:
            assert user is None
            assert (
                await session.scalar(
                    select(SocialIdentity).where(SocialIdentity.user_id == user_id)
                )
                is None
            )
            assert (
                await session.scalar(select(InboundEvent).where(InboundEvent.user_id == user_id))
                is None
            )
        else:
            assert user.deleted_at is not None


async def test_complete_deletion_http_purge_replay_and_fresh_account(deletion):
    ingress, worker, runner, stub = deletion
    await confirm(worker.flow)
    original = message(text="Explain my chart")
    old_event = await ingress.accept(original)
    await worker.process(old_event)
    user_id = (await row(worker, old_event)).user_id
    async with worker.database.transaction() as session:
        session_id = (await session.get(ConversationSession, user_id)).session_id
    scope = ContextScope(user_id=user_id, session_id=session_id)
    await runner.context.remember(scope, "concise_readings")
    assert stub.memories and stub.sessions
    # Unrelated owner must survive both local and remote cleanup.
    _, other_event = await send(ingress, worker, user="43", command="start")
    other_id = (await row(worker, other_event)).user_id
    user_id, job_id, confirmation, confirmation_id = await request(ingress, worker)
    await worker.redis.set(f"oria:user:{user_id}:conversation-lock", "synthetic-old-lease", ex=120)
    await worker.redis.set(
        f"oria:user:{other_id}:conversation-lock", "synthetic-other-lease", ex=120
    )
    for sender in ("42", "43"):
        for kind in ("rate", "notice"):
            await worker.redis.set(f"oria:abuse:telegram:{sender}:{kind}", "1", ex=60)
    with pytest.raises(UserUnavailableError):
        await ingress.accept(message(text="private late text"))
    await runner.recover()
    await assert_local_erased(worker, user_id, completed=True)
    job = await job_for(worker, user_id)
    assert job.status == "completed" and job.completed_at
    assert job.encrypted_target is None and job.confirmation_token is None
    assert not stub.memories and not stub.sessions and f"oria:{user_id}" in stub.purged
    with pytest.raises(ContextUnavailable):
        await runner.context.respond(scope, ConversationRequest(filtered_message="Tell me more"))
    assert worker.client.send_text.call_args.args == ("42", FINAL_TEXT)
    assert not await worker.redis.exists(f"oria:user:{user_id}:conversation-lock")
    assert await worker.redis.exists(f"oria:user:{other_id}:conversation-lock")
    for kind in ("rate", "notice"):
        assert not await worker.redis.exists(f"oria:abuse:telegram:42:{kind}")
        assert await worker.redis.exists(f"oria:abuse:telegram:43:{kind}")
        await worker.redis.delete(f"oria:abuse:telegram:43:{kind}")
    await worker.redis.delete(f"oria:user:{other_id}:conversation-lock")
    count = worker.client.send_text.await_count
    await runner.process(job_id)
    await worker.process(await ingress.accept(confirmation))
    await worker.process(await ingress.accept(original))
    assert worker.client.send_text.await_count == count
    assert (await row(worker, confirmation_id)).user_id is None
    async with worker.database.transaction() as session:
        assert await session.get(User, other_id) is not None
        assert (
            await session.scalar(select(SocialIdentity).where(SocialIdentity.user_id == user_id))
            is None
        )
    _, new_event = await send(ingress, worker, command="start")
    new_id = (await row(worker, new_event)).user_id
    assert new_id != user_id and "Policy" in worker.client.send_text.call_args.args[1]
    async with worker.database.transaction() as session:
        assert await session.scalar(select(Consent).where(Consent.user_id == new_id)) is None
    # A newly clicked old button must not delete the new account.
    await send(ingress, worker, callback=confirmation.callback_data)
    assert "stale" in worker.client.send_text.call_args.args[1]
    assert await job_for(worker, new_id) is None


@pytest.mark.parametrize("dependency", ["context", "redis"])
async def test_dependency_failure_preserves_progress_and_retries(deletion, dependency):
    ingress, worker, runner, _ = deletion
    await confirm(worker.flow)
    user_id, job_id, _, _ = await request(ingress, worker)
    actual_context, actual_redis = runner.context, runner.redis
    if dependency == "context":
        runner.context = AsyncMock()
        runner.context.purge.side_effect = ContextUnavailable("synthetic")
    else:
        runner.redis = AsyncMock()
        runner.redis.delete.side_effect = ConnectionError("synthetic")
    await runner.recover()
    await assert_local_erased(worker, user_id, completed=False)
    job = await job_for(worker, user_id)
    assert job.status == ("local_deleted" if dependency == "context" else "context_deleted")
    assert job.attempts == 1 and job.failure_code == "deletion_retry"
    await runner.process(job_id)
    assert (await job_for(worker, user_id)).attempts == 1  # Enforce backoff.
    runner.context, runner.redis = actual_context, actual_redis
    await make_due(worker, job_id)
    await runner.recover()
    await assert_local_erased(worker, user_id, completed=True)


async def test_notification_failure_does_not_restore_identity_and_expires(deletion):
    ingress, worker, runner, _ = deletion
    user_id, job_id, _, _ = await request(ingress, worker)
    worker.client.send_text.side_effect = RuntimeError("synthetic send failure")
    await runner.process(job_id)
    await assert_local_erased(worker, user_id, completed=True)
    job = await job_for(worker, user_id)
    assert job.status == "completed" and job.encrypted_target and job.failure_code
    assert job.encrypted_target != b"42"
    async with worker.database.transaction() as session:
        stored = await session.get(DeletionJob, job_id)
        stored.notification_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await make_due(worker, job_id)
    calls = worker.client.send_text.await_count
    await runner.recover()
    assert worker.client.send_text.await_count == calls
    assert (await job_for(worker, user_id)).encrypted_target is None


async def test_notification_retry_without_repeating_purge(deletion):
    ingress, worker, runner, stub = deletion
    user_id, job_id, _, _ = await request(ingress, worker)
    worker.client.send_text.side_effect = RuntimeError("synthetic")
    await runner.process(job_id)
    calls = len(stub.requests)
    worker.client.send_text.side_effect = None
    await make_due(worker, job_id)
    await runner.recover()
    assert len(stub.requests) == calls
    assert (await job_for(worker, user_id)).encrypted_target is None
    assert worker.client.send_text.call_args.args[1] == FINAL_TEXT


async def test_confirmation_is_scoped_cancellable_expiring_and_requires_no_consent(deletion):
    ingress, worker, runner, stub = deletion
    _, identifier = await send(ingress, worker, command="delete_me")
    user_id = (await row(worker, identifier)).user_id
    buttons = worker.client.send_text.call_args.kwargs["buttons"]
    await runner.recover()
    assert (await job_for(worker, user_id)).status == "confirmation" and not stub.requests
    await send(ingress, worker, callback=buttons[0].data, user="43")
    assert "stale" in worker.client.send_text.call_args.args[1]
    await send(ingress, worker, callback=buttons[1].data)
    assert await job_for(worker, user_id) is None
    await send(ingress, worker, callback=buttons[0].data)
    assert "stale" in worker.client.send_text.call_args.args[1]
    await send(ingress, worker, command="delete_me")
    token = worker.client.send_text.call_args.kwargs["buttons"][0].data
    async with worker.database.transaction() as session:
        job = await session.scalar(select(DeletionJob).where(DeletionJob.user_id == user_id))
        job.confirmation_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await send(ingress, worker, callback=token)
    assert "stale" in worker.client.send_text.call_args.args[1]
    await runner.recover()
    assert await job_for(worker, user_id) is None


async def test_queued_work_and_concurrent_deletion_workers_are_harmless(deletion):
    ingress, worker, runner, stub = deletion
    await confirm(worker.flow)
    _, prompt = await send(ingress, worker, command="delete_me")
    user_id = (await row(worker, prompt)).user_id
    button = worker.client.send_text.call_args.kwargs["buttons"][0].data
    confirmation = await ingress.accept(message(callback=button))
    queued = await ingress.accept(message(text="Explain my chart"))
    await worker.process(confirmation)
    job = await job_for(worker, user_id)
    await asyncio.gather(runner.process(job.id), runner.process(job.id), worker.process(queued))
    await runner.recover()
    assert all(r.url.path.endswith("/v1/subjects/purge") for r in stub.requests)
    await assert_local_erased(worker, user_id, completed=True)
    assert (await row(worker, queued)).encrypted_input is None
    # A delayed worker holding an old owner UUID cannot send a reply or recreate a key.
    await worker.calculate(queued, user_id)
    await worker.deliver(queued, user_id)
    await worker.failed(queued, user_id)


async def test_ambiguous_purge_and_process_restart_repeat_same_subject(deletion):
    ingress, worker, runner, stub = deletion
    user_id, job_id, confirmation, _ = await request(ingress, worker)
    # Redelivery before cleanup also does not repeat confirmation or create a second job.
    await worker.process(await ingress.accept(confirmation))
    assert await runner.step(job_id)  # Local erasure committed; simulate process death.
    context = runner.context

    async def ambiguous(subject):
        await context.purge(subject)
        raise ContextUnavailable("synthetic lost acknowledgement")

    runner.context = AsyncMock()
    runner.context.purge.side_effect = ambiguous
    await runner.process(job_id)
    assert f"oria:{user_id}" in stub.purged
    assert (await job_for(worker, user_id)).status == "local_deleted"
    restarted = DeletionWorker(
        worker.database, worker.redis, worker.encryption, context, worker.client
    )
    await make_due(worker, job_id)
    await restarted.recover()
    await assert_local_erased(worker, user_id, completed=True)
    purges = [r for r in stub.requests if r.url.path.endswith("/v1/subjects/purge")]
    assert len(purges) == 2 and purges[0].content == purges[1].content


async def test_confirmation_waits_for_inflight_work_then_fences_later_work(deletion):
    ingress, worker, runner, _ = deletion
    await confirm(worker.flow)
    _, prompt = await send(ingress, worker, command="delete_me")
    user_id = (await row(worker, prompt)).user_id
    button = worker.client.send_text.call_args.kwargs["buttons"][0].data
    entered, release = asyncio.Event(), asyncio.Event()

    async def inflight():
        async with worker.database.transaction() as session:
            await session.execute(
                select(User).where(User.id == user_id).with_for_update(key_share=True)
            )
            entered.set()
            await release.wait()

    running = asyncio.create_task(inflight())
    await asyncio.wait_for(entered.wait(), 5)
    confirmation = await ingress.accept(message(callback=button))
    confirming = asyncio.create_task(worker.process(confirmation))
    try:
        await asyncio.sleep(0.1)
        assert not confirming.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(running, confirming), 5)
        with pytest.raises(UserUnavailableError):
            await ingress.accept(message(text="Explain my chart"))
        await runner.recover()
        await assert_local_erased(worker, user_id, completed=True)
    finally:
        release.set()
        await asyncio.gather(running, confirming)


async def test_development_downgrade_after_completed_deletion(deletion, infrastructure):
    ingress, worker, runner, _ = deletion
    user_id, _, _, event_id = await request(ingress, worker)
    await runner.recover()
    assert (await row(worker, event_id)).user_id is None
    migrate(infrastructure[0], "downgrade", "0007")
    migrate(infrastructure[0], "upgrade", "head")
    migrate(infrastructure[0], "check")
    async with worker.database.transaction() as session:
        assert await session.get(InboundEvent, event_id) is None
        assert await session.get(User, user_id) is None
