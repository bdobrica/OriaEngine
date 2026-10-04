"""Operational v1 output: fixed dimensions, parseable stdout and explicit unknowns."""

import json
import logging
from unittest.mock import AsyncMock, patch

import pytest

from oria_engine.config import Settings
from oria_engine.observability import METRICS, JsonFormatter
from oria_engine.operations import GAUGES, run


@pytest.mark.parametrize("database_ok,redis_ok", [(True, True), (False, True), (True, False)])
async def test_cli_v1_shape_exit_status_and_cleanup(database_ok, redis_ok, capsys):
    database, redis = AsyncMock(), AsyncMock()
    redis.ping.return_value = redis_ok
    gauges = dict.fromkeys(GAUGES, 0)
    with (
        patch("oria_engine.operations.Database", return_value=database),
        patch("oria_engine.operations.Redis.from_url", return_value=redis),
        patch("oria_engine.operations.database_gauges", new_callable=AsyncMock) as read,
    ):
        read.return_value = gauges
        if not database_ok:
            read.side_effect = RuntimeError("synthetic private database details")
        code = await run(Settings(_env_file=None))
    assert code == (0 if database_ok and redis_ok else 1)
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 1
    result = json.loads(output)
    assert set(result) == {"version", "checks", "gauges"}
    assert result["version"] == 1
    assert result["checks"] == {"database": database_ok, "redis": redis_ok}
    assert set(result["gauges"]) == {
        "queue_pending",
        "queue_processing",
        "queue_ready",
        "queue_sent",
        "queue_dead",
        "queue_depth",
        "queue_oldest_age_seconds",
        "users",
        "consent_accepted",
        "consent_declined",
        "consent_revoked",
        "onboarding_drafts",
        "onboarding_confirmed",
        "onboarding_chart_cached",
        "deletion_confirmation",
        "deletion_requested",
        "deletion_local_deleted",
        "deletion_context_deleted",
        "deletion_redis_deleted",
        "deletion_completed",
        "deletion_retrying",
        "deletion_oldest_age_seconds",
    }
    assert set(result["gauges"].values()) == ({0} if database_ok else {None})
    assert "private" not in output
    database.close.assert_awaited_once()
    redis.aclose.assert_awaited_once()


def test_log_metric_catalog_matches_v1_and_never_projects_extra_dimensions():
    assert {
        "database_transaction",
        "queue_admission",
        "queue_publish",
        "worker_dispatch",
        "worker_process",
        "worker_retry",
        "worker_dead",
        "mcp_natal",
        "mcp_transits",
        "second_context_respond",
        "second_context_remember",
        "second_context_purge",
        "telegram_send",
        "telegram_update",
        "update_deduplicated",
        "inbound_limited",
        "consent_disclosure",
        "policy_input_block",
        "policy_output_block",
        "policy_high_stakes",
        "deletion_process",
        "deletion_retry",
    } == METRICS
    record = logging.LogRecord("test", logging.INFO, "", 0, "metric", (), None)
    record.metric_name = "mcp_natal"
    record.outcome = "error"
    record.error_category = "mcp"
    record.duration_ms = 10.5
    record.latitude = 51.5
    record.message_text = "synthetic private message"
    sample = json.loads(JsonFormatter().format(record))
    assert set(sample) == {
        "timestamp",
        "level",
        "event",
        "correlation_id",
        "duration_ms",
        "metric_name",
        "outcome",
        "error_category",
        "value",
    }
    assert sample["value"] == 1
