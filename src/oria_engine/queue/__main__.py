"""make worker: four worker threads plus PostgreSQL recovery every five seconds."""

import asyncio
import logging
import signal
import sys
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
from oria_engine.observability import configure_logging, correlation_scope
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
                ConversationContext(context, settings.oria_policy_version),
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
    try:
        for identifier in await recoverable(database):
            await asyncio.to_thread(publisher.send, str(identifier))
    finally:
        await database.close()


def run(settings: Settings) -> None:
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
    }:
        raise ConfigurationError("Set ORIA_POLICY_VERSION=2026-10-03.1 for conversation storage")
    resolver = LocalPlaceResolver()
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
        logger.info("application_started")
        while not stop.is_set():
            try:
                asyncio.run(recover(settings, publisher))
            except Exception:
                logger.error("queue_unavailable")
            stop.wait(5)
    finally:
        worker.stop(timeout=70000)
        publisher.close()
        logger.info("application_stopped")


def main() -> None:
    try:
        settings = load_settings()
        configure_logging(settings)
        run(settings)
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print("Worker failed; check service configuration and connectivity", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
