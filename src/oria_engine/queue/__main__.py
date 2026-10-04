"""make worker: four worker threads plus PostgreSQL recovery every five seconds."""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from threading import Event
from uuid import UUID

import dramatiq
from aiogram import Bot
from dramatiq import Worker
from redis.asyncio import Redis

from oria_engine.astrology.client import FastMCPAstrologyClient
from oria_engine.config import ConfigurationError, Settings, load_settings
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.context.service import ConversationContext
from oria_engine.db.session import Database
from oria_engine.domain.consent import ConsentFlow
from oria_engine.domain.onboarding import OnboardingFlow
from oria_engine.domain.places import LocalPlaceResolver
from oria_engine.observability import configure_logging, correlation_scope, startup_summary
from oria_engine.privacy.deletion import DeletionWorker
from oria_engine.privacy.encryption import ProfileEncryption
from oria_engine.queue.broker import Publisher
from oria_engine.queue.events import EventWorker, recoverable
from oria_engine.telegram.adapter import TelegramChannelClient

logger = logging.getLogger(__name__)


async def process(settings: Settings, resolver: LocalPlaceResolver, event_id: str) -> None:
    database = Database(settings)
    bot = Bot(settings.telegram_bot_token.get_secret_value())
    redis = Redis.from_url(
        settings.redis_url.get_secret_value(), socket_timeout=3, socket_connect_timeout=3
    )
    context = SecondContextProvider(settings)
    try:
        encryption = ProfileEncryption(settings)
        flow = ConsentFlow(
            database,
            settings.oria_policy_version,
            OnboardingFlow(
                encryption,
                settings.oria_policy_version,
                resolver,
                FastMCPAstrologyClient(settings.astrology_mcp_url),
                ConversationContext(
                    context, settings.oria_policy_version, enabled=settings.llm_processing_enabled
                ),
            ),
        )
        await EventWorker(database, redis, encryption, flow, TelegramChannelClient(bot)).process(
            UUID(event_id)
        )
    finally:
        await context.aclose()
        await redis.aclose()
        await bot.session.close()
        await database.close()


async def recover(settings: Settings, publisher: Publisher) -> None:
    database = Database(settings)
    bot = Bot(settings.telegram_bot_token.get_secret_value())
    redis = Redis.from_url(
        settings.redis_url.get_secret_value(), socket_timeout=3, socket_connect_timeout=3
    )
    context = SecondContextProvider(settings)
    try:
        # Direct PostgreSQL recovery also works while the Redis broker is unavailable.
        await DeletionWorker(
            database, redis, ProfileEncryption(settings), context, TelegramChannelClient(bot)
        ).recover()
        for identifier in await recoverable(database):
            await asyncio.to_thread(publisher.send, str(identifier))
    finally:
        await context.aclose()
        await redis.aclose()
        await bot.session.close()
        await database.close()


def run(settings: Settings, *, health_file: Path | None = None) -> None:
    ProfileEncryption(settings)
    if not settings.telegram_bot_token.get_secret_value():
        raise ConfigurationError("Worker requires TELEGRAM_BOT_TOKEN")
    if settings.oria_policy_version in {
        "2026-09-01",
        "2026-09-28",
        "2026-09-28.1",
        "2026-09-28.2",
        "2026-09-28.3",
        "2026-10-03",
        "2026-10-03.1",
    }:
        raise ConfigurationError("Set ORIA_POLICY_VERSION=2026-10-03.2 for conversation storage")
    resolver = LocalPlaceResolver()
    if health_file is not None:
        health_file.unlink(missing_ok=True)
    publisher = Publisher(settings)
    stop = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    @dramatiq.actor(
        broker=publisher.broker, actor_name="process_inbound", queue_name="inbound", max_retries=0
    )
    def process_inbound(event_id: str) -> None:
        with correlation_scope():
            try:
                asyncio.run(process(settings, resolver, event_id))
            except Exception:
                # Database/Redis outages and hard crashes recover from the durable lease.
                logger.error("worker_retry")

    worker = Worker(publisher.broker, worker_threads=4)
    try:
        worker.start()
        startup_summary(settings, "worker")
        logger.info("application_started")
        while not stop.is_set():
            try:
                asyncio.run(recover(settings, publisher))
            except Exception:
                logger.error("queue_unavailable")
            if health_file is not None:
                health_file.touch()
            stop.wait(5)
    finally:
        if health_file is not None:
            health_file.unlink(missing_ok=True)
        worker.stop(timeout=70000)
        publisher.close()
        logger.info("application_stopped")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-file", type=Path)
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        configure_logging(settings)
        run(settings, health_file=args.health_file)
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print("Worker failed; check service configuration and connectivity", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
