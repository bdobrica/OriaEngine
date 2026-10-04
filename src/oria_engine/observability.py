"""Allowlisted operational logs: never pass birth profiles or user text to logging."""

import json
import logging
import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import uuid4

from oria_engine.config import Settings

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
update_id: ContextVar[int | None] = ContextVar("update_id", default=None)
EVENTS = frozenset(
    {
        "application_started",
        "application_stopped",
        "request_completed",
        "request_failed",
        "update_completed",
        "update_failed",
        "inbound_limited",
        "queue_unavailable",
        "worker_retry",
        "worker_dead",
        "worker_lock_lost",
    }
)


@contextmanager
def correlation_scope(*, telegram_update_id: int | None = None) -> Iterator[str]:
    """Use around a request or normalized update; always restore the parent context."""
    identifier = uuid4().hex
    correlation_token = correlation_id.set(identifier)
    update_token = update_id.set(telegram_update_id)
    try:
        yield identifier
    finally:
        update_id.reset(update_token)
        correlation_id.reset(correlation_token)


def redact_secrets(text: str, secrets: tuple[str, ...]) -> str:
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        # Never interpolate arbitrary messages, args, extra objects, or exception/stack text.
        event = record.msg if isinstance(record.msg, str) and record.msg in EVENTS else "log_record"
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": logging.getLevelName(record.levelno),
            "event": event,
            "correlation_id": correlation_id.get(),
        }
        if update_id.get() is not None:
            payload["update_id"] = update_id.get()
        status = getattr(record, "status_code", None)
        if type(status) is int and 100 <= status <= 599:
            payload["status_code"] = status
        duration = getattr(record, "duration_ms", None)
        if (
            (type(duration) is int or type(duration) is float)
            and 0 <= duration <= 2**63
            and math.isfinite(duration)
        ):
            payload["duration_ms"] = duration
        # Redact before JSON escaping as configured values can contain quotes/backslashes.
        for name, value in payload.items():
            if isinstance(value, str):
                payload[name] = redact_secrets(value, self.secrets)
        return json.dumps(payload, allow_nan=False)


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(settings.secret_values()))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)
    # Uvicorn's own handlers otherwise bypass the application's privacy boundary.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
