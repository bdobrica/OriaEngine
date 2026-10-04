"""Allowlisted operational logs: never pass birth profiles or user text to logging."""

import asyncio
import json
import logging
import math
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from time import perf_counter
from typing import Any, ParamSpec, TypeVar
from uuid import UUID, uuid4

from oria_engine.config import Settings

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
update_id: ContextVar[int | None] = ContextVar("update_id", default=None)
job_id: ContextVar[UUID | None] = ContextVar("job_id", default=None)
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
        "deletion_retry",
        "metric",
        "configuration_summary",
        "job_admitted",
    }
)

# Static dimensions only. IDs remain log context, never metric labels.
METRICS = frozenset(
    {
        "database_transaction",
        "queue_admission",
        "queue_publish",
        "worker_process",
        "worker_dispatch",
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
    }
)
OUTCOMES = frozenset({"success", "error", "cancelled"})
ERROR_CATEGORIES = frozenset(
    {"database", "redis", "mcp", "second_context", "telegram", "timeout", "limited", "internal"}
)
P = ParamSpec("P")
T = TypeVar("T")


def error_category(error: BaseException) -> str:
    # Lazy imports avoid cycles with database and boundary modules.
    from aiogram.exceptions import TelegramAPIError
    from redis.exceptions import RedisError
    from sqlalchemy.exc import SQLAlchemyError

    from oria_engine.astrology.client import AstrologyUnavailable
    from oria_engine.context.contracts import ContextUnavailable
    from oria_engine.queue.limits import AdmissionRejected

    for kind, name in (
        (SQLAlchemyError, "database"),
        (RedisError, "redis"),
        (AstrologyUnavailable, "mcp"),
        (ContextUnavailable, "second_context"),
        (TelegramAPIError, "telegram"),
        (TimeoutError, "timeout"),
        (AdmissionRejected, "limited"),
    ):
        if isinstance(error, kind):
            return name
    return "internal"


def count(name: str) -> None:
    if name not in METRICS:
        raise ValueError("Unknown operational metric")
    logging.getLogger(__name__).info("metric", extra={"metric_name": name, "outcome": "success"})


@contextmanager
def measurement(name: str) -> Iterator[None]:
    """One log sample per attempt, with elapsed time and a fixed error category."""
    if name not in METRICS:
        raise ValueError("Unknown operational metric")
    started = perf_counter()
    outcome = "success"
    category = None
    try:
        yield
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except Exception as exc:
        outcome, category = "error", error_category(exc)
        raise
    finally:
        logging.getLogger(__name__).log(
            logging.WARNING if outcome == "error" else logging.INFO,
            "metric",
            extra={
                "metric_name": name,
                "outcome": outcome,
                "error_category": category,
                "duration_ms": round((perf_counter() - started) * 1000, 3),
            },
        )


def observed(
    name: str,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Coroutine[Any, Any, T]]]:
    def decorate(function: Callable[P, Awaitable[T]]) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            with measurement(name):
                return await function(*args, **kwargs)

        return wrapped

    return decorate


def startup_summary(settings: Settings, role: str) -> None:
    logging.getLogger(__name__).info(
        "configuration_summary",
        extra={
            "app_env": settings.app_env,
            "role": role,
            "webhook_enabled": bool(settings.telegram_webhook_secret.get_secret_value()),
            "llm_enabled": settings.llm_processing_enabled,
            "context_auth_enabled": bool(settings.second_context_bearer_token.get_secret_value()),
        },
    )


@contextmanager
def correlation_scope(
    *, telegram_update_id: int | None = None, internal_job_id: UUID | None = None
) -> Iterator[str]:
    """Use around a request or normalized update; always restore the parent context."""
    identifier = uuid4().hex
    correlation_token = correlation_id.set(identifier)
    update_token = update_id.set(telegram_update_id)
    job_token = job_id.set(internal_job_id)
    try:
        yield identifier
    finally:
        job_id.reset(job_token)
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
        identifier = job_id.get()
        if event == "job_admitted":
            identifier = getattr(record, "job_id", identifier)
        if isinstance(identifier, UUID):
            payload["job_id"] = str(identifier)
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
        if event == "metric":
            name = getattr(record, "metric_name", None)
            outcome = getattr(record, "outcome", None)
            category = getattr(record, "error_category", None)
            if isinstance(name, str) and name in METRICS:
                payload["metric_name"] = name
            if isinstance(outcome, str) and outcome in OUTCOMES:
                payload["outcome"] = outcome
            if isinstance(category, str) and category in ERROR_CATEGORIES:
                payload["error_category"] = category
            payload["value"] = 1
        if event == "configuration_summary":
            environment = getattr(record, "app_env", None)
            if isinstance(environment, str) and environment in {
                "development",
                "test",
                "production",
            }:
                payload["app_env"] = environment
            role = getattr(record, "role", None)
            if isinstance(role, str) and role in {"gateway", "polling", "worker"}:
                payload["role"] = role
            for name in ("webhook_enabled", "llm_enabled", "context_auth_enabled"):
                value = getattr(record, name, None)
                if type(value) is bool:
                    payload[name] = value
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
