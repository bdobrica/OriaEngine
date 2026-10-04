"""Real Redis counters and canonical PostgreSQL backlog under concurrent admission."""

import asyncio
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from redis import Redis
from redis.exceptions import ConnectionError
from sqlalchemy import func, select

from oria_engine.config import Settings
from oria_engine.context.contracts import ContextUnavailable
from oria_engine.db.models import InboundEvent, User
from oria_engine.queue.broker import Publisher
from oria_engine.queue.events import recoverable
from oria_engine.queue.limits import UNAVAILABLE_REPLY, AdmissionRejected, InboundLimits

from .test_conversation_worker import conversation as conversation
from .test_queue import due, message, row
from .test_queue import queue as queue


@pytest.fixture
async def controlled(queue):
    ingress, worker = queue
    config = worker.redis.connection_pool.connection_kwargs
    client = Redis(host=config["host"], port=config["port"], socket_timeout=3)
    keys = [
        f"oria:abuse:telegram:{sender}:{kind}"
        for sender in ("42", "43", "44")
        for kind in ("rate", "notice")
    ]
    await worker.redis.delete(*keys)
    ingress.limits = InboundLimits(client, Settings(_env_file=None))
    try:
        yield ingress, worker, client
    finally:
        await worker.redis.delete(*keys)
        client.close()


async def test_atomic_redis_window_across_replicas_and_expiry(controlled):
    ingress, worker, client = controlled
    other = InboundLimits(client, Settings(_env_file=None))
    admitted = await asyncio.gather(
        *((ingress.limits if i % 2 else other).admit("telegram", "42") for i in range(40))
    )
    assert sum(admitted) == 20
    assert 0 < await worker.redis.ttl("oria:abuse:telegram:42:rate") <= 60
    assert await other.admit("telegram", "43")
    await worker.redis.pexpire("oria:abuse:telegram:42:rate", 1)
    await asyncio.sleep(0.02)
    assert await other.admit("telegram", "42")


async def test_concurrent_burst_caps_backlog_and_other_user_runs(controlled):
    ingress, worker, _ = controlled
    results = await asyncio.gather(
        *(ingress.accept(message()) for _ in range(16)), return_exceptions=True
    )
    assert sum(isinstance(result, UUID) for result in results) == 8
    assert sum(isinstance(result, AdmissionRejected) for result in results) == 8
    assert sum(bool(r.reply) for r in results if isinstance(r, AdmissionRejected)) == 1
    first = await ingress.accept(message(user="43"))
    await worker.process(first)
    assert (await row(worker, first)).status == "sent"
    # Redis loss resets counters but cannot increase this user's canonical backlog.
    await worker.redis.flushdb()
    with pytest.raises(AdmissionRejected):
        await ingress.accept(message())
    async with worker.database.transaction() as session:
        assert await session.scalar(select(func.count()).select_from(InboundEvent)) == 9


async def test_duplicates_do_not_charge_budget_and_completion_frees_capacity(controlled):
    ingress, worker, _ = controlled
    ingress.limits.backlog = 1
    inbound = message()
    first = await ingress.accept(inbound)
    assert await ingress.publishable(first)
    for _ in range(5):
        assert await ingress.accept(inbound) == first
    assert await worker.redis.get("oria:abuse:telegram:42:rate") == b"1"
    with pytest.raises(AdmissionRejected):
        await ingress.accept(message())
    await worker.process(first)
    assert not await ingress.publishable(first)
    second = await ingress.accept(message())
    assert second != first
    assert await ingress.publishable(second)


@pytest.mark.parametrize("text", ["x" * 4097, "😀" * 2049, "\ud800"])
async def test_oversized_input_creates_no_identity_or_event(controlled, text):
    ingress, worker, _ = controlled
    with pytest.raises(AdmissionRejected):
        await ingress.accept(message(text=text))
    async with worker.database.transaction() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 0
        assert await session.scalar(select(func.count()).select_from(InboundEvent)) == 0
    assert not await worker.redis.exists("oria:abuse:telegram:42:rate")


async def test_redis_failure_fails_closed_without_durable_admission(controlled):
    ingress, worker, _ = controlled
    ingress.limits.admit = AsyncMock(side_effect=ConnectionError("synthetic"))
    with pytest.raises(ConnectionError):
        await ingress.accept(message())
    async with worker.database.transaction() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 0


async def test_recovery_scan_selects_one_head_per_user_even_at_large_legacy_depth(queue):
    ingress, worker = queue
    first = await ingress.accept(message())
    for _ in range(101):
        await ingress.accept(message())
    other = await ingress.accept(message(user="43"))
    assert await recoverable(worker.database) == [first, other]
    await worker.process(other)
    assert (await row(worker, other)).status == "sent"


async def test_final_unavailable_reply_rolls_back_partial_domain_mutation(controlled):
    from datetime import UTC, datetime

    ingress, worker, _ = controlled
    identifier = await ingress.accept(message())
    async with worker.database.transaction() as session:
        event = await session.get(InboundEvent, identifier)
        event.attempts = 4

    async def partial(session, user_id, *args, **kwargs):
        user = await session.get(User, user_id)
        user.deleted_at = datetime.now(UTC)
        await session.flush()
        raise ContextUnavailable()

    worker.flow.handle_in_session = partial
    await worker.process(identifier)
    event = await row(worker, identifier)
    assert event.status == "sent"
    async with worker.database.transaction() as session:
        assert (await session.get(User, event.user_id)).deleted_at is None
    assert worker.client.send_text.call_args.args[1] == UNAVAILABLE_REPLY


async def test_emergency_disable_keeps_profile_and_privacy_commands_available(conversation):
    from .test_astrology_profiles import confirm

    ingress, worker, astrology, provider = conversation
    await confirm(worker.flow)
    worker.flow.onboarding.context.enabled = False
    await worker.process(await ingress.accept(message(text="Explain my natal chart")))
    assert worker.client.send_text.call_args.args[1] == UNAVAILABLE_REPLY
    await worker.process(await ingress.accept(message(), command="profile"))
    assert "1990-04-13" in worker.client.send_text.call_args.args[1]
    await worker.process(await ingress.accept(message(), command="privacy"))
    assert worker.client.send_text.call_args.kwargs["buttons"]
    provider.respond.assert_not_called()
    provider.purge.assert_not_called()


async def test_repeated_context_failure_backoff_and_final_local_reply(controlled):
    ingress, worker, _ = controlled
    worker.flow.handle_in_session = AsyncMock(side_effect=ContextUnavailable("synthetic-private"))
    identifier = await ingress.accept(message())
    for attempt in range(1, 6):
        await due(worker, identifier)
        await worker.process(identifier)
        event = await row(worker, identifier)
        assert event.attempts == attempt
        if attempt < 5:
            assert event.status == "pending"
            delay = (event.next_attempt_at - event.created_at).total_seconds()
            assert delay >= 5 * 2**attempt
            await worker.process(identifier)
            assert (await row(worker, identifier)).attempts == attempt
        else:
            assert event.status == "sent" and event.encrypted_input is None
            worker.client.send_text.assert_awaited_once()
            assert worker.client.send_text.call_args.args[1] == UNAVAILABLE_REPLY


async def test_publication_reservation_prevents_replay_job_flood_and_recovers(controlled):
    ingress, worker, client = controlled
    publisher = Publisher(
        Settings(
            _env_file=None,
            redis_url=f"redis://{client.connection_pool.connection_kwargs['host']}:"
            f"{client.connection_pool.connection_kwargs['port']}/0",
        )
    )
    publisher.broker.enqueue = Mock()
    identifier = await ingress.accept(message())
    try:
        await asyncio.gather(
            *(asyncio.to_thread(publisher.send, str(identifier)) for _ in range(12))
        )
        publisher.broker.enqueue.assert_called_once()
        assert 0 < await worker.redis.ttl(f"oria:event:{identifier}:publication") <= 150
        await worker.process(identifier)
        assert not await worker.redis.exists(f"oria:event:{identifier}:publication")
        next_id = str(uuid4())
        publisher.broker.enqueue.side_effect = RuntimeError("synthetic")
        with pytest.raises(RuntimeError):
            await asyncio.to_thread(publisher.send, next_id)
        assert not await worker.redis.exists(f"oria:event:{next_id}:publication")
        publisher.broker.enqueue.side_effect = None
        await asyncio.to_thread(publisher.send, next_id)
    finally:
        publisher.close()
