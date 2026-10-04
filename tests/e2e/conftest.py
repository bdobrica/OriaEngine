import base64
import secrets
from contextlib import AsyncExitStack

import httpx
import pytest
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from redis.asyncio import Redis
from sqlalchemy import text

from oria_engine.app import create_app
from oria_engine.astrology.client import FastMCPAstrologyClient
from oria_engine.config import Settings
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.context.service import ConversationContext
from oria_engine.domain.consent import ConsentFlow
from oria_engine.domain.onboarding import OnboardingFlow
from oria_engine.domain.places import LocalPlaceResolver
from oria_engine.privacy.encryption import ProfileEncryption
from oria_engine.queue.broker import Publisher
from oria_engine.queue.events import EventIngress, EventWorker
from oria_engine.queue.limits import InboundLimits
from oria_engine.telegram.adapter import TelegramChannelClient
from oria_engine.telegram.webhook import WebhookGateway
from tests.support.http_fakes import SecondContextFake, TelegramFake, serve
from tests.support.infrastructure import astrology_container as astrology_container
from tests.support.infrastructure import database as database
from tests.support.infrastructure import infrastructure as infrastructure
from tests.support.infrastructure import isolated_settings as isolated_settings
from tests.support.infrastructure import migrate
from tests.support.replay import Replay


@pytest.fixture
async def replay(database, infrastructure, astrology_container):
    migrate(infrastructure[0], "upgrade", "head")
    # Only the per-session randomly named Compose database can reach this cleanup.
    async with database.transaction() as session:
        await session.execute(text("TRUNCATE deletion_jobs, inbound_events, users CASCADE"))
    token = "123456:" + secrets.token_hex(24)
    secret = secrets.token_hex(24)
    telegram = TelegramFake(token)
    context = SecondContextFake(secrets.token_hex(24))
    async with AsyncExitStack() as resources:
        telegram_url = await resources.enter_async_context(serve(telegram.app))
        context_url = await resources.enter_async_context(serve(context.app))
        settings = Settings(
            _env_file=None,
            app_env="test",
            database_url=infrastructure[0],
            redis_url=infrastructure[1],
            telegram_bot_token=token,
            telegram_webhook_secret=secret,
            oria_policy_version="2026-10-03.2",
            profile_encryption_key=base64.b64encode(AESGCM.generate_key(bit_length=256)).decode(),
            second_context_base_url=context_url,
            second_context_bearer_token=context.stub.token,
            second_context_subject_namespace="oria",
            astrology_mcp_url=astrology_container,
            inbound_rate_per_minute=120,
        )
        encryption = ProfileEncryption(settings)
        redis = Redis.from_url(infrastructure[1])
        resources.push_async_callback(redis.aclose)
        await redis.flushdb()
        bot = Bot(token, session=AiohttpSession(api=TelegramAPIServer.from_base(telegram_url)))
        resources.push_async_callback(bot.session.close)
        provider = SecondContextProvider(settings)
        resources.push_async_callback(provider.aclose)
        flow = ConsentFlow(
            database,
            settings.oria_policy_version,
            OnboardingFlow(
                encryption,
                settings.oria_policy_version,
                LocalPlaceResolver(),
                FastMCPAstrologyClient(astrology_container),
                ConversationContext(provider, settings.oria_policy_version),
            ),
        )
        publisher = Publisher(settings)
        resources.callback(publisher.close)
        ingress = EventIngress(
            database,
            encryption,
            flow.policy_version,
            limits=InboundLimits(publisher.client, settings),
        )
        worker = EventWorker(database, redis, encryption, flow, TelegramChannelClient(bot))
        app = create_app(settings, webhook_gateway=WebhookGateway(bot, ingress, publisher))
        await resources.enter_async_context(app.router.lifespan_context(app))
        client = await resources.enter_async_context(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://replay",
                headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            )
        )
        harness = Replay(client, publisher, worker, telegram, context)
        resources.callback(harness.consumer.close)
        yield harness
