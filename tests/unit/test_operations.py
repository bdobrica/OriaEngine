import asyncio
import io
import json
import logging
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendMessage
from redis.exceptions import ConnectionError
from sqlalchemy.exc import OperationalError

from oria_engine.astrology.client import AstrologyUnavailable, FastMCPAstrologyClient
from oria_engine.config import Settings
from oria_engine.context.contracts import ContextReply, ContextUnavailable, ConversationRequest
from oria_engine.context.service import ConversationContext
from oria_engine.observability import (
    JsonFormatter,
    configure_logging,
    correlation_scope,
    job_id,
    measurement,
    observed,
    startup_summary,
)
from oria_engine.operations import GAUGES, main, snapshot
from tests.unit.test_astrology_client import request


@pytest.fixture
def log_stream():
    configure_logging(Settings(_env_file=None))
    stream = io.StringIO()
    logging.getLogger().handlers[0].setStream(stream)
    return stream


def samples(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


@pytest.mark.parametrize(
    "error,category",
    [
        (OperationalError("private SQL", {"private": "payload"}, Exception("private")), "database"),
        (ConnectionError("private redis"), "redis"),
        (AstrologyUnavailable("private chart"), "mcp"),
        (ContextUnavailable("private transcript"), "second_context"),
        (TelegramNetworkError(SendMessage(chat_id=42, text="private"), "private"), "telegram"),
        (TimeoutError("private timeout"), "timeout"),
        (RuntimeError("private unexpected"), "internal"),
    ],
)
def test_fixed_failure_categories_no_exception_payload(log_stream, error, category):
    identifier = uuid4()
    with (
        correlation_scope(internal_job_id=identifier),
        pytest.raises(type(error)),
        measurement("worker_process"),
    ):
        raise error
    sample = samples(log_stream)[0]
    assert sample["job_id"] == str(identifier)
    assert sample["metric_name"] == "worker_process"
    assert sample["outcome"] == "error"
    assert sample["error_category"] == category
    assert sample["duration_ms"] >= 0
    assert "private" not in log_stream.getvalue()
    assert job_id.get() is None


async def test_success_and_cancellation_preserve_behavior(log_stream):
    @observed("second_context_respond")
    async def call(cancel=False):
        if cancel:
            raise asyncio.CancelledError
        return "private returned data"

    assert await call() == "private returned data"
    with pytest.raises(asyncio.CancelledError):
        await call(True)
    assert [s["outcome"] for s in samples(log_stream)] == ["success", "cancelled"]
    assert "private" not in log_stream.getvalue()


async def test_real_mcp_boundary_reports_validation_failure(log_stream):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.call_tool.return_value.is_error = False
    client.call_tool.return_value.structured_content = {"private": "private chart"}
    with (
        patch("oria_engine.astrology.client.Client", return_value=client),
        pytest.raises(AstrologyUnavailable),
    ):
        await FastMCPAstrologyClient("http://test/mcp").calculate_natal_chart(request())
    assert samples(log_stream)[0]["metric_name"] == "mcp_natal"
    assert samples(log_stream)[0]["error_category"] == "mcp"
    assert "private" not in log_stream.getvalue()


def test_startup_summary_omits_urls_versions_secrets(log_stream):
    settings = Settings(
        _env_file=None,
        telegram_bot_token="123:synthetic-private-token",
        second_context_bearer_token="synthetic-private-context",
        llm_processing_enabled=False,
        oria_policy_version="private-version",
        astrology_mcp_url="http://private.example/mcp",
    )
    startup_summary(settings, "worker")
    sample = samples(log_stream)[0]
    assert sample["role"] == "worker"
    assert sample["app_env"] == "development"
    assert sample["llm_enabled"] is False
    assert sample["context_auth_enabled"] is True
    assert "private" not in log_stream.getvalue()


def test_formatter_rejects_arbitrary_metric_dimensions():
    record = logging.LogRecord("test", logging.INFO, "", 0, "metric", (), None)
    record.metric_name = "private-message"
    record.error_category = {"private": "profile"}
    record.outcome = "private"
    record.user_id = uuid4()
    record.profile = "private"
    sample = JsonFormatter().format(record)
    assert "private" not in sample
    assert "user_id" not in sample
    record.msg = "configuration_summary"
    record.role = []
    record.app_env = {}
    assert "private" not in JsonFormatter().format(record)


@pytest.mark.parametrize("database_ok,redis_ok", [(True, True), (False, True), (True, False)])
async def test_snapshot_dependencies_independent_missing_is_unknown(database_ok, redis_ok):
    redis = AsyncMock()
    redis.ping.return_value = redis_ok
    gauges = dict.fromkeys(GAUGES, 0)
    with patch("oria_engine.operations.database_gauges", new_callable=AsyncMock) as read:
        if database_ok:
            read.return_value = gauges
        else:
            read.side_effect = RuntimeError("private database")
        result = await snapshot(AsyncMock(), redis)
    assert result["checks"] == {"database": database_ok, "redis": redis_ok}
    assert set(result["gauges"]) == set(GAUGES)
    assert all(v == (0 if database_ok else None) for v in result["gauges"].values())
    assert "private" not in json.dumps(result)


async def test_snapshot_cancellation_propagates():
    with (
        patch("oria_engine.operations.database_gauges", side_effect=asyncio.CancelledError),
        pytest.raises(asyncio.CancelledError),
    ):
        await snapshot(AsyncMock(), AsyncMock())


def test_cli_failure_does_not_print_validation_inputs(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "private-invalid-value")
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert "private" not in capsys.readouterr().err


def test_job_context_nested_restores_parent():
    outer, inner = uuid4(), uuid4()
    with correlation_scope(internal_job_id=outer):
        with correlation_scope(internal_job_id=inner):
            assert job_id.get() == inner
        assert job_id.get() == outer
    assert job_id.get() is None


def test_admission_log_links_update_context_to_only_typed_internal_job_id(log_stream):
    identifier = uuid4()
    with correlation_scope(telegram_update_id=123):
        logging.getLogger(__name__).info("job_admitted", extra={"job_id": identifier})
        logging.getLogger(__name__).info("job_admitted", extra={"job_id": "private-untrusted"})
    linked, ignored = samples(log_stream)
    assert linked["update_id"] == 123
    assert linked["job_id"] == str(identifier)
    assert "job_id" not in ignored
    assert "private" not in log_stream.getvalue()


@pytest.mark.parametrize(
    "message,draft,metric",
    [
        ("Tell me more", "Tell me your email.", "policy_output_block"),
        ("Will I die today?", "unused", "policy_high_stakes"),
    ],
)
async def test_policy_branches_count_without_logging_text(log_stream, message, draft, metric):
    provider = AsyncMock()
    provider.respond.return_value = ContextReply(response_id="synthetic", text=draft)
    with patch("oria_engine.context.service.ConversationSessionRepository") as repository:
        repository.return_value.get_or_create = AsyncMock()
        await ConversationContext(provider, "test-v1").respond(
            AsyncMock(), uuid4(), ConversationRequest(filtered_message=message)
        )
    assert [s["metric_name"] for s in samples(log_stream)] == [metric]
    assert message not in log_stream.getvalue()
    assert draft not in log_stream.getvalue()
