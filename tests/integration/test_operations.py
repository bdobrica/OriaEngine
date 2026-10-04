import io
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from oria_engine.config import Settings
from oria_engine.db.models import DeletionJob, InboundEvent
from oria_engine.observability import configure_logging
from oria_engine.operations import database_gauges, snapshot

from .test_queue import message, row
from .test_queue import queue as queue


async def test_durable_snapshot_dedup_funnel_and_worker_job_context(queue):
    ingress, worker = queue
    configure_logging(Settings(_env_file=None))
    stream = io.StringIO()
    logging.getLogger().handlers[0].setStream(stream)
    baseline = await database_gauges(worker.database)
    inbound = message(text="private birth profile", callback=worker.flow.buttons[0].data)
    identifier = await ingress.accept(inbound)
    assert await ingress.accept(inbound) == identifier
    async with worker.database.transaction() as session:
        event = await session.get(InboundEvent, identifier)
        event.created_at = datetime.now(UTC) - timedelta(seconds=90)
    pending = await database_gauges(worker.database)
    assert pending["queue_depth"] == baseline["queue_depth"] + 1
    assert pending["queue_oldest_age_seconds"] >= 90
    await worker.process(identifier)
    done = await snapshot(worker.database, worker.redis)
    assert done["checks"] == {"database": True, "redis": True}
    assert done["gauges"]["queue_depth"] == baseline["queue_depth"]
    assert done["gauges"]["consent_accepted"] == baseline["consent_accepted"] + 1
    assert done["gauges"]["queue_sent"] == baseline["queue_sent"] + 1
    samples = [json.loads(s) for s in stream.getvalue().splitlines()]
    assert sum(s.get("metric_name") == "update_deduplicated" for s in samples) == 1
    attempts = [s for s in samples if s.get("metric_name") == "worker_process"]
    assert len(attempts) == 1
    assert attempts[0]["job_id"] == str(identifier)
    assert "private" not in stream.getvalue()
    assert "private" not in json.dumps(done)


async def test_worker_failure_category_and_retry_keep_durable_job_id(queue):
    ingress, worker = queue
    configure_logging(Settings(_env_file=None))
    stream = io.StringIO()
    logging.getLogger().handlers[0].setStream(stream)
    identifier = await ingress.accept(message())
    worker.client.send_text.side_effect = TimeoutError("private send payload")
    await worker.process(identifier)
    async with worker.database.transaction() as session:
        event = await session.get(InboundEvent, identifier)
        event.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    worker.client.send_text.side_effect = None
    await worker.process(identifier)
    attempts = [json.loads(s) for s in stream.getvalue().splitlines()]
    attempts = [s for s in attempts if s.get("metric_name") == "worker_process"]
    assert [s["outcome"] for s in attempts] == ["error", "success"]
    assert attempts[0]["error_category"] == "timeout"
    assert {s["job_id"] for s in attempts} == {str(identifier)}
    assert "private" not in stream.getvalue()


async def test_deletion_progress_snapshot_uses_only_aggregate_metadata(queue):
    ingress, worker = queue
    identifier = await ingress.accept(message())
    user_id = (await row(worker, identifier)).user_id
    async with worker.database.transaction() as session:
        job = DeletionJob(
            user_id=user_id,
            status="local_deleted",
            attempts=2,
            requested_at=datetime.now(UTC) - timedelta(seconds=120),
            next_attempt_at=datetime.now(UTC),
            failure_code="deletion_retry",
        )
        session.add(job)
    try:
        gauges = await database_gauges(worker.database)
        assert gauges["deletion_local_deleted"] >= 1
        assert gauges["deletion_retrying"] >= 1
        assert gauges["deletion_oldest_age_seconds"] >= 120
        assert str(user_id) not in json.dumps(gauges)
        async with worker.database.transaction() as session:
            stored = await session.scalar(select(DeletionJob).where(DeletionJob.user_id == user_id))
            assert stored.attempts == 2
            assert stored.status == "local_deleted"
    finally:
        async with worker.database.transaction() as session:
            stored = await session.scalar(select(DeletionJob).where(DeletionJob.user_id == user_id))
            await session.delete(stored)
