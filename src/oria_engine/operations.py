"""Private operator snapshot: aggregate canonical metadata, never payloads or identities."""

import asyncio
import json
import sys
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import cast

from redis.asyncio import Redis
from sqlalchemy import func, select, text

from oria_engine.config import ConfigurationError, Settings, load_settings
from oria_engine.db.models import (
    AstrologyProfile,
    BirthProfile,
    Consent,
    DeletionJob,
    InboundEvent,
    OnboardingProgress,
    User,
)
from oria_engine.db.session import Database
from oria_engine.observability import configure_logging

EVENT_STATES = ("pending", "processing", "ready", "sent", "dead")
DELETION_STATES = (
    "confirmation",
    "requested",
    "local_deleted",
    "context_deleted",
    "redis_deleted",
    "completed",
)
GAUGES = (
    *(f"queue_{s}" for s in EVENT_STATES),
    "queue_depth",
    "queue_oldest_age_seconds",
    "users",
    "consent_accepted",
    "consent_declined",
    "consent_revoked",
    "onboarding_drafts",
    "onboarding_confirmed",
    "onboarding_chart_cached",
    *(f"deletion_{s}" for s in DELETION_STATES),
    "deletion_retrying",
    "deletion_oldest_age_seconds",
)


async def database_gauges(database: Database) -> dict[str, int | float]:
    async with database.transaction() as session:
        # The snapshot cannot mutate canonical state, and uses one consistent view.
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout = '3000ms'"))
        result: dict[str, int | float] = {}
        now = datetime.now(UTC)
        for prefix, model, states in (
            ("queue", InboundEvent, EVENT_STATES),
            ("deletion", DeletionJob, DELETION_STATES),
        ):
            totals = (
                await session.execute(
                    select(
                        *(func.count().filter(model.status == state) for state in states)
                    ).select_from(model)
                )
            ).one()
            result.update({f"{prefix}_{s}": int(n) for s, n in zip(states, totals, strict=True)})
        result["queue_depth"] = sum(result[f"queue_{s}"] for s in EVENT_STATES[:3])
        oldest = await session.scalar(
            select(func.min(InboundEvent.created_at)).where(
                InboundEvent.status.in_(EVENT_STATES[:3])
            )
        )
        result["queue_oldest_age_seconds"] = max(0, (now - oldest).total_seconds()) if oldest else 0
        # Latest consent per retained user, all policy versions; no historical revision inflation.
        latest = (
            select(Consent.user_id, func.max(Consent.revision).label("revision"))
            .group_by(Consent.user_id)
            .subquery()
        )
        consent_totals = (
            await session.execute(
                select(
                    *(
                        func.count().filter(Consent.status == s)
                        for s in ("accepted", "declined", "revoked")
                    )
                )
                .select_from(Consent)
                .join(
                    latest,
                    (Consent.user_id == latest.c.user_id) & (Consent.revision == latest.c.revision),
                )
            )
        ).one()
        result.update(
            {
                f"consent_{s}": int(n)
                for s, n in zip(("accepted", "declined", "revoked"), consent_totals, strict=True)
            }
        )
        for name, table in (
            ("users", User),
            ("onboarding_drafts", OnboardingProgress),
            ("onboarding_confirmed", BirthProfile),
            ("onboarding_chart_cached", AstrologyProfile),
        ):
            result[name] = int(await session.scalar(select(func.count()).select_from(table)) or 0)
        unfinished = DeletionJob.status.in_(DELETION_STATES[1:-1])
        result["deletion_retrying"] = int(
            await session.scalar(
                select(func.count()).where(unfinished, DeletionJob.failure_code.is_not(None))
            )
            or 0
        )
        oldest_deletion = await session.scalar(
            select(func.min(DeletionJob.requested_at)).where(unfinished)
        )
        result["deletion_oldest_age_seconds"] = (
            max(0, (now - oldest_deletion).total_seconds()) if oldest_deletion else 0
        )
        return result


async def snapshot(database: Database, redis: Redis) -> dict[str, object]:
    async def storage() -> tuple[bool, dict[str, int | float | None]]:
        try:
            async with asyncio.timeout(10):
                return True, dict(await database_gauges(database))
        except Exception:
            return False, dict.fromkeys(GAUGES)

    async def coordination() -> bool:
        try:
            async with asyncio.timeout(3):
                return await cast(Awaitable[bool], redis.ping()) is True
        except Exception:
            return False

    (database_ok, gauges), redis_ok = await asyncio.gather(storage(), coordination())
    return {"version": 1, "checks": {"database": database_ok, "redis": redis_ok}, "gauges": gauges}


async def run(settings: Settings) -> int:
    database = Database(settings)
    redis = Redis.from_url(
        settings.redis_url.get_secret_value(), socket_timeout=3, socket_connect_timeout=3
    )
    try:
        result = await snapshot(database, redis)
        print(json.dumps(result, allow_nan=False))
        return 0 if result["checks"] == {"database": True, "redis": True} else 1
    finally:
        await redis.aclose()
        await database.close()


def main() -> None:
    try:
        settings = load_settings()
        configure_logging(settings)
        code = asyncio.run(run(settings))
    except ConfigurationError:
        print("Invalid operator configuration", file=sys.stderr)
        code = 1
    except Exception:
        print("Operator snapshot unavailable", file=sys.stderr)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
