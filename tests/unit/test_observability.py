import base64
import io
import json
import logging
import secrets

import pytest

from oria_engine.config import Settings
from oria_engine.observability import (
    JsonFormatter,
    configure_logging,
    correlation_id,
    correlation_scope,
    redact_secrets,
    update_id,
)


def test_redaction_handles_empty_overlapping_and_escaped_secrets():
    assert redact_secrets('abc abcdef a"b', ("", "abc", "abcdef", 'a"b')) == (
        "[REDACTED] [REDACTED] [REDACTED]"
    )


def test_no_configured_secrets_or_payloads_in_output(monkeypatch):
    values = {
        name: secrets.token_urlsafe(32)
        for name in (
            "TELEGRAM_WEBHOOK_SECRET",
            "SECOND_CONTEXT_BEARER_TOKEN",
        )
    }
    values["TELEGRAM_BOT_TOKEN"] = "123:" + secrets.token_urlsafe(32)
    values["PROFILE_ENCRYPTION_KEY"] = base64.b64encode(secrets.token_bytes(32)).decode()
    password = secrets.token_urlsafe(32)
    values["DATABASE_URL"] = f"postgresql+psycopg://oria:{password}@localhost/oria"
    values["REDIS_URL"] = f"redis://:{password}@localhost/0"
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    settings = Settings()
    configure_logging(settings)
    stream = io.StringIO()
    handler = logging.getLogger().handlers[0]
    handler.setStream(stream)
    payload = {"birth_date": "1990-01-02", "birth_time": "12:34", "birthplace": "private-place"}
    for name in ("oria_engine", "uvicorn.error", "httpx"):
        logger = logging.getLogger(name)
        logger.warning("%s %s", values, payload, extra={"profile": payload})
        try:
            raise RuntimeError(str(values) + str(payload))
        except RuntimeError:
            logger.exception("request_failed", stack_info=True)
    output = stream.getvalue()
    for value in [*values.values(), password, *payload.values()]:
        assert value not in output
    assert len([json.loads(line) for line in output.splitlines()]) == 6


def test_correlation_restores_parent_and_records_update():
    with correlation_scope(telegram_update_id=123) as outer:
        record = logging.LogRecord("test", logging.INFO, "", 0, "request_completed", (), None)
        result = json.loads(JsonFormatter().format(record))
        assert result["correlation_id"] == outer
        assert result["update_id"] == 123
        with correlation_scope() as inner:
            assert inner != outer
            assert update_id.get() is None
        assert correlation_id.get() == outer
    assert correlation_id.get() is None
    assert update_id.get() is None


@pytest.mark.parametrize(
    "duration", [float("nan"), float("inf"), -1, 10**5000], ids=["nan", "inf", "negative", "huge"]
)
def test_invalid_numeric_extras_cannot_trigger_unsafe_logging_fallback(duration):
    record = logging.LogRecord("test", logging.INFO, "", 0, "private message", (), None)
    record.duration_ms = duration
    record.status_code = "private status"
    result = json.loads(JsonFormatter().format(record))
    assert result["event"] == "log_record"
    assert "duration_ms" not in result
    assert "status_code" not in result
