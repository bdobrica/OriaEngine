import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr
from redis.asyncio import Redis
from redis.exceptions import LockNotOwnedError
from sqlalchemy import delete, select

from oria_engine.config import Settings
from oria_engine.db.models import (
    BirthProfile,
    Consent,
    ConversationSession,
    InboundEvent,
    OnboardingProgress,
    SocialIdentity,
    User,
)
from oria_engine.db.repositories import ConsentRepository
from oria_engine.domain.channel import ChannelMessage
from oria_engine.domain.consent import ConsentFlow
from oria_engine.privacy.encryption import ProfileEncryption
from oria_engine.queue.events import EventIngress, EventWorker, InputPayload, recoverable

from .conftest import migrate


@pytest.fixture
async def queue(database, infrastructure):
    migrate(infrastructure[0], "upgrade", "head")
    encryption = ProfileEncryption(
        Settings(
            _env_file=None,
            profile_encryption_key=SecretStr("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="),
        )
    )
    # Earlier integration checks restart Redis; Docker may assign a new ephemeral port.
    port = infrastructure[2]("port", "redis", "6379").rsplit(":", 1)[1]
    redis = Redis.from_url(f"redis://127.0.0.1:{port}/0")
    flow = ConsentFlow(database, "test-queue-v1")
    client = AsyncMock()
    ingress = EventIngress(database, encryption, flow.policy_version)
    worker = EventWorker(database, redis, encryption, flow, client)
    try:
        yield ingress, worker
    finally:
        await redis.aclose()
        async with database.transaction() as session:
            for model in (
                InboundEvent,
                ConversationSession,
                OnboardingProgress,
                BirthProfile,
                Consent,
                SocialIdentity,
                User,
            ):
                await session.execute(delete(model))


def message(user="42", text="synthetic private input", callback=None):
    return ChannelMessage(
        "telegram", user, user, "1", str(uuid4()), datetime.now(UTC), text, callback
    )


async def row(worker, identifier):
    async with worker.database.transaction() as session:
        return await session.get(InboundEvent, identifier)


async def due(worker, identifier):
    async with worker.database.transaction() as session:
        event = await session.get(InboundEvent, identifier)
        event.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)


async def consent_rows(worker):
    async with worker.database.transaction() as session:
        return list(await session.scalars(select(Consent).order_by(Consent.revision)))


async def test_duplicate_updates_discard_preconsent_text_and_jobs_mutate_once(queue):
    ingress, worker = queue
    inbound = message(callback=worker.flow.buttons[0].data)
    identifiers = await asyncio.gather(*(ingress.accept(inbound) for _ in range(4)))
    assert len(set(identifiers)) == 1
    identifier = identifiers[0]
    event = await row(worker, identifier)
    payload = InputPayload.model_validate_json(
        worker.decrypt(event, event.encrypted_input, "input")
    )
    assert payload.message.text == ""
    assert b"synthetic private input" not in event.encrypted_input
    await asyncio.gather(*(worker.process(identifier) for _ in range(4)))
    await worker.process(identifier)
    assert len(await consent_rows(worker)) == 1
    worker.client.send_text.assert_awaited_once()
    event = await row(worker, identifier)
    assert (
        event.status == "sent" and event.encrypted_input is None and event.encrypted_reply is None
    )
    # Delayed replay of accept after decline must not change the later decision.
    declined = await ingress.accept(message(callback=worker.flow.buttons[1].data))
    await worker.process(declined)
    await worker.process(await ingress.accept(inbound))
    assert [c.status for c in await consent_rows(worker)] == ["accepted", "declined"]


async def test_send_failure_retries_reply_without_repeating_domain_action(queue):
    ingress, worker = queue
    identifier = await ingress.accept(message(callback=worker.flow.buttons[0].data))
    original = worker.flow.handle_in_session
    worker.flow.handle_in_session = AsyncMock(wraps=original)
    worker.client.send_text.side_effect = RuntimeError("secret must not be retained")
    await worker.process(identifier)
    event = await row(worker, identifier)
    assert event.status == "ready" and event.encrypted_reply and event.encrypted_input is None
    assert event.attempts == 1 and event.failure_code == "processing_failed"
    await worker.process(identifier)  # Backoff cannot be bypassed by duplicate deliveries.
    assert (await row(worker, identifier)).attempts == 1
    worker.client.send_text.side_effect = None
    await due(worker, identifier)
    await worker.process(identifier)
    assert (await row(worker, identifier)).status == "sent"
    assert len(await consent_rows(worker)) == 1
    worker.flow.handle_in_session.assert_awaited_once()


async def test_transit_snapshot_survives_delivery_retry(queue, birth_payload):
    from astrology_mcp.engine import calculate, calculate_transits

    from oria_engine.domain.onboarding import OnboardingFlow

    from .test_astrology_profiles import confirm

    ingress, worker = queue
    astrology = AsyncMock()
    astrology.calculate_natal_chart.side_effect = calculate
    astrology.calculate_transits.side_effect = calculate_transits
    resolver = AsyncMock()
    resolver.resolve.return_value = (birth_payload.birth_place,)
    worker.flow.onboarding = OnboardingFlow(
        worker.encryption, worker.flow.policy_version, resolver, astrology
    )
    await confirm(worker.flow)
    inbound = message(text="today")
    identifier = await ingress.accept(inbound)
    worker.client.send_text.side_effect = RuntimeError("synthetic send failure")
    await worker.process(identifier)
    assert (await row(worker, identifier)).status == "ready"
    astrology.calculate_transits.assert_awaited_once()
    assert (
        astrology.calculate_transits.call_args.args[0].target_timestamp_utc == inbound.received_at
    )
    original_reply = worker.client.send_text.call_args
    worker.client.send_text.side_effect = None
    await due(worker, identifier)
    await worker.process(identifier)
    await worker.process(identifier)
    assert (await row(worker, identifier)).status == "sent"
    assert worker.client.send_text.call_args == original_reply
    astrology.calculate_transits.assert_awaited_once()


async def test_rollback_and_crashed_claim_recover(queue):
    ingress, worker = queue
    identifier = await ingress.accept(message(callback=worker.flow.buttons[0].data))
    original = worker.flow.handle_in_session

    async def fail_after_mutation(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("synthetic crash before commit")

    worker.flow.handle_in_session = fail_after_mutation
    await worker.process(identifier)
    assert await consent_rows(worker) == []
    assert (await row(worker, identifier)).encrypted_input
    await due(worker, identifier)
    event = await row(worker, identifier)
    assert await worker.claim(identifier, event.user_id)
    assert identifier not in await recoverable(worker.database)
    # Simulate dead process: claim persisted, no domain commit, recovery lease elapsed.
    await due(worker, identifier)
    assert identifier in await recoverable(worker.database)
    worker.flow.handle_in_session = original
    await worker.process(identifier)
    assert len(await consent_rows(worker)) == 1
    assert (await row(worker, identifier)).status == "sent"


async def test_crash_after_domain_commit_resends_without_mutating(queue):
    ingress, worker = queue
    identifier = await ingress.accept(message(callback=worker.flow.buttons[0].data))
    event = await row(worker, identifier)
    assert await worker.claim(identifier, event.user_id)
    await worker.calculate(identifier, event.user_id)
    assert (await row(worker, identifier)).status == "ready"
    worker.flow.handle_in_session = AsyncMock(side_effect=AssertionError("must not repeat"))
    await due(worker, identifier)
    await worker.process(identifier)
    assert (await row(worker, identifier)).status == "sent"
    worker.flow.handle_in_session.assert_not_called()


async def test_same_user_order_and_other_users_concurrent_even_after_redis_loss(queue):
    ingress, worker = queue
    first = await ingress.accept(message(callback=worker.flow.buttons[0].data))
    second = await ingress.accept(message(callback=worker.flow.buttons[1].data))
    other = await ingress.accept(message(user="43", callback=worker.flow.buttons[0].data))
    entered = asyncio.Event()
    release = asyncio.Event()
    original = worker.flow.handle_in_session

    async def pause(session, user_id, inbound, **kwargs):
        if inbound.provider_user_id == "42":
            entered.set()
            await release.wait()
        return await original(session, user_id, inbound, **kwargs)

    worker.flow.handle_in_session = pause
    running = asyncio.create_task(worker.process(first))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        # New ingress for this user must not wait for slow computation's user lock.
        third = await asyncio.wait_for(ingress.accept(message()), 2)
        await worker.process(second)  # Redis contention: no attempt consumed.
        assert (await row(worker, second)).attempts == 0
        await worker.redis.flushdb()  # Redis is disposable, PG transaction still owns user fence.
        blocked = asyncio.create_task(worker.process(second))
        await asyncio.wait_for(worker.process(other), 3)
        assert (await row(worker, other)).status == "sent"
        assert not blocked.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(running, blocked), 5)
        await worker.process(second)
        assert (await row(worker, second)).status == "sent"
        await worker.process(third)
        assert [
            c.status
            for c in await consent_rows(worker)
            if c.user_id == (await row(worker, first)).user_id
        ] == ["accepted", "declined"]
    finally:
        release.set()
        await running


async def test_pending_event_order_and_redis_flush_recovery(queue):
    ingress, worker = queue
    first = await ingress.accept(message(callback=worker.flow.buttons[0].data))
    second = await ingress.accept(message(callback=worker.flow.buttons[1].data))
    await worker.process(second)
    assert (await row(worker, second)).attempts == 0
    await worker.redis.flushdb()
    assert await recoverable(worker.database) == [first]
    await worker.process(first)
    assert await recoverable(worker.database) == [second]
    await worker.process(second)
    assert [c.status for c in await consent_rows(worker)] == ["accepted", "declined"]


async def test_attempt_limit_and_expiry_scrub_payloads(queue):
    ingress, worker = queue
    identifier = await ingress.accept(message())
    worker.client.send_text.side_effect = RuntimeError("secret")
    for _ in range(5):
        await due(worker, identifier)
        await worker.process(identifier)
    event = await row(worker, identifier)
    assert event.status == "dead" and event.attempts == 5
    assert event.encrypted_reply is None and event.encrypted_input is None
    assert identifier not in await recoverable(worker.database)
    expired = await ingress.accept(message())
    async with worker.database.transaction() as session:
        event = await session.get(InboundEvent, expired)
        event.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert expired not in await recoverable(worker.database)
    event = await row(worker, expired)
    assert event.status == "dead" and event.failure_code == "expired"
    assert event.encrypted_input is None


async def test_consent_change_suppresses_pending_reply_and_encrypts_after_consent(queue):
    ingress, worker = queue
    accepted = await ingress.accept(message(callback=worker.flow.buttons[0].data))
    await worker.process(accepted)
    inbound = message(text="1990-01-02")
    identifier = await ingress.accept(inbound)
    event = await row(worker, identifier)
    assert b"1990-01-02" not in event.encrypted_input
    assert "1990-01-02" in worker.decrypt(event, event.encrypted_input, "input")
    assert await worker.claim(identifier, event.user_id)
    await worker.calculate(identifier, event.user_id)
    async with worker.database.transaction() as session:
        await ConsentRepository(session).revoke(event.user_id, "telegram")
    worker.client.send_text.reset_mock()
    await due(worker, identifier)
    await worker.process(identifier)
    assert (await row(worker, identifier)).failure_code == "consent_changed"
    worker.client.send_text.assert_not_called()


async def test_lock_release_cannot_remove_new_owner(queue):
    _, worker = queue
    key = f"oria:test:lock:{uuid4()}"
    old = worker.redis.lock(key, timeout=0.05, thread_local=False)
    new = worker.redis.lock(key, timeout=5, thread_local=False)
    assert await old.acquire(blocking=False)
    await asyncio.sleep(0.1)
    assert await new.acquire(blocking=False)
    with pytest.raises(LockNotOwnedError):
        await old.release()
    assert await new.owned()
    await new.release()


async def test_encrypted_events_cannot_be_swapped(queue):
    ingress, worker = queue
    identifier = await ingress.accept(message())
    event = await row(worker, identifier)
    from oria_engine.privacy.encryption import ProfileEncryptionError

    with pytest.raises(ProfileEncryptionError):
        worker.encryption.decrypt_event(
            event.encrypted_input,
            user_id=event.user_id,
            event_id=uuid4(),
            kind="input",
            key_version=event.encryption_key_version,
        )


async def test_real_dramatiq_broker_delivers_identifier_to_production_job(queue, infrastructure):
    from unittest.mock import patch

    import dramatiq
    from dramatiq import Worker

    from oria_engine.queue.__main__ import process, recover
    from oria_engine.queue.broker import Publisher

    ingress, worker = queue
    settings = Settings(
        _env_file=None,
        database_url=infrastructure[0],
        redis_url=f"redis://127.0.0.1:{worker.redis.connection_pool.connection_kwargs['port']}/0",
        profile_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        telegram_bot_token="123456:synthetic-test-token",
        oria_policy_version=worker.flow.policy_version,
    )
    publisher = Publisher(settings)
    bot = AsyncMock()
    received = []

    @dramatiq.actor(
        broker=publisher.broker, actor_name="process_inbound", queue_name="inbound", max_retries=0
    )
    def actor(identifier):
        received.append(identifier)
        asyncio.run(process(settings, AsyncMock(), identifier))

    consumer = Worker(publisher.broker, worker_threads=2)
    identifier = await ingress.accept(message(callback=worker.flow.buttons[0].data))
    try:
        with patch("oria_engine.queue.__main__.Bot", return_value=bot):
            consumer.start()
            # Recovery repairs the deliberate gap between PostgreSQL commit and enqueue.
            await recover(settings, publisher)
            async with asyncio.timeout(15):
                while (await row(worker, identifier)).status != "sent":
                    await asyncio.sleep(0.1)
        assert received == [str(identifier)]
        bot.send_message.assert_awaited_once()
        assert len(await consent_rows(worker)) == 1
    finally:
        await asyncio.to_thread(consumer.stop, timeout=10000)
        publisher.close()


async def test_timeout_rolls_back_and_releases_lock(queue, monkeypatch):
    ingress, worker = queue
    identifier = await ingress.accept(message(callback=worker.flow.buttons[0].data))
    original = worker.flow.handle_in_session

    async def slow(*args, **kwargs):
        await original(*args, **kwargs)
        await asyncio.sleep(5)

    worker.flow.handle_in_session = slow
    monkeypatch.setattr("oria_engine.queue.events.PROCESS_SECONDS", 0.1)
    await worker.process(identifier)
    event = await row(worker, identifier)
    assert event.status == "pending" and event.attempts == 1
    assert await consent_rows(worker) == []
    assert not await worker.redis.exists(f"oria:user:{event.user_id}:conversation-lock")


async def test_duplicate_onboarding_job_preserves_draft_revision(queue):
    from oria_engine.db.onboarding import OnboardingRepository
    from oria_engine.domain.onboarding import OnboardingFlow

    ingress, worker = queue
    worker.flow.onboarding = OnboardingFlow(
        worker.encryption, worker.flow.policy_version, AsyncMock()
    )
    accepted = await ingress.accept(message(callback=worker.flow.buttons[0].data))
    await worker.process(accepted)
    inbound = message(text="1990-04-13")
    identifier = await ingress.accept(inbound)
    await worker.process(identifier)
    user_id = (await row(worker, identifier)).user_id
    async with worker.database.transaction() as session:
        before = await OnboardingRepository(
            session, worker.encryption, worker.flow.policy_version
        ).get(user_id)
    await worker.process(await ingress.accept(inbound))
    async with worker.database.transaction() as session:
        after = await OnboardingRepository(
            session, worker.encryption, worker.flow.policy_version
        ).get(user_id)
    assert after == before and after.birth_date.isoformat() == "1990-04-13"
    await worker.redis.flushdb()
    async with worker.database.transaction() as session:
        restored = await OnboardingRepository(
            session, worker.encryption, worker.flow.policy_version
        ).get(user_id)
    assert restored == before
