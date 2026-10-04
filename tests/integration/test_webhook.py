import asyncio
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest
from aiogram import Bot
from sqlalchemy import select

from oria_engine.app import create_app
from oria_engine.config import Settings
from oria_engine.db.models import Consent, InboundEvent, SocialIdentity, User
from oria_engine.queue.broker import Publisher
from oria_engine.queue.events import InputPayload, recoverable
from oria_engine.telegram.webhook import WEBHOOK_PATH, WebhookGateway

from .test_queue import queue as queue


@pytest.fixture
async def webhook(queue, infrastructure):
    ingress, worker = queue
    await worker.redis.flushdb()
    settings = Settings(
        _env_file=None,
        database_url=infrastructure[0],
        redis_url=f"redis://127.0.0.1:{worker.redis.connection_pool.connection_kwargs['port']}/0",
        profile_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        telegram_bot_token="123456:synthetic-webhook-token",
        telegram_webhook_secret="synthetic-webhook-secret",
        oria_policy_version=worker.flow.policy_version,
    )
    publisher = Publisher(settings)
    bot = Bot(settings.telegram_bot_token.get_secret_value())
    app = create_app(settings, webhook_gateway=WebhookGateway(bot, ingress, publisher))
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            client.headers["X-Telegram-Bot-Api-Secret-Token"] = "synthetic-webhook-secret"
            yield client, publisher, worker
    finally:
        await bot.session.close()
        publisher.close()


def update(identifier=101, text="/start", callback=None):
    message = {
        "message_id": 12,
        "date": int(datetime.now(UTC).timestamp()),
        "chat": {"id": 42, "type": "private"},
        "from": {"id": 42, "is_bot": False, "first_name": "Synthetic"},
        "text": text,
    }
    if callback is None:
        return {"update_id": identifier, "message": message}
    message["from"] = {"id": 123456, "is_bot": True, "first_name": "Bot"}
    return {
        "update_id": identifier,
        "callback_query": {
            "id": "synthetic-callback",
            "chat_instance": "synthetic",
            "from": {"id": 42, "is_bot": False, "first_name": "Synthetic"},
            "message": message,
            "data": callback,
        },
    }


async def events(worker):
    async with worker.database.transaction() as session:
        return list(await session.scalars(select(InboundEvent)))


async def test_concurrent_webhook_replays_create_one_event_and_one_domain_action(webhook):
    client, publisher, worker = webhook
    inbound = update(callback=worker.flow.buttons[0].data)
    responses = await asyncio.gather(*(client.post(WEBHOOK_PATH, json=inbound) for _ in range(4)))
    assert all(response.status_code == 200 for response in responses)
    stored = await events(worker)
    assert len(stored) == 1
    identifier = stored[0].id
    consumer = publisher.broker.consume("inbound", timeout=100)
    try:
        for _ in responses:
            job = await asyncio.to_thread(next, consumer)
            assert job.actor_name == "process_inbound"
            assert job.args == (str(identifier),)
            assert job.kwargs == {}
            await worker.process(identifier)
            consumer.ack(job)
    finally:
        consumer.close()
    worker.client.send_text.assert_awaited_once()
    async with worker.database.transaction() as session:
        assert len(list(await session.scalars(select(Consent)))) == 1
        assert len(list(await session.scalars(select(User)))) == 1
        assert len(list(await session.scalars(select(SocialIdentity)))) == 1
    assert (await events(worker))[0].encrypted_input is None
    assert (await client.post(WEBHOOK_PATH, json=inbound)).status_code == 200
    await worker.process(identifier)
    worker.client.send_text.assert_awaited_once()


async def test_queue_failure_keeps_committed_event_and_retry_reuses_it(webhook):
    client, publisher, worker = webhook
    with patch.object(publisher, "send", side_effect=RuntimeError("synthetic unavailable")):
        response = await client.post(WEBHOOK_PATH, json=update())
    assert response.status_code == 503
    stored = await events(worker)
    assert len(stored) == 1
    identifier = stored[0].id
    assert identifier in await recoverable(worker.database)
    assert (await client.post(WEBHOOK_PATH, json=update())).status_code == 200
    assert len(await events(worker)) == 1
    await worker.process(identifier)
    assert (await events(worker))[0].status == "sent"
    worker.client.send_text.assert_awaited_once()


async def test_database_failure_returns_503_and_provider_retry_admits_once(webhook):
    client, publisher, worker = webhook
    with (
        patch.object(
            worker.database, "transaction", side_effect=RuntimeError("synthetic unavailable")
        ),
        patch.object(publisher, "send", wraps=publisher.send) as send,
    ):
        assert (await client.post(WEBHOOK_PATH, json=update())).status_code == 503
        send.assert_not_called()
    assert await events(worker) == []
    assert (await client.post(WEBHOOK_PATH, json=update())).status_code == 200
    assert len(await events(worker)) == 1


async def test_preconsent_input_and_telegram_metadata_do_not_enter_storage(webhook):
    client, _, worker = webhook
    inbound = update(text="synthetic private birth values")
    inbound["message"]["from"]["username"] = "synthetic_username"
    assert (await client.post(WEBHOOK_PATH, json=inbound)).status_code == 200
    event = (await events(worker))[0]
    decoded = InputPayload.model_validate_json(
        worker.decrypt(event, event.encrypted_input, "input")
    )
    assert decoded.message.text == ""
    assert "synthetic_username" not in decoded.model_dump_json()
    assert decoded.command is None


async def test_untrusted_requests_create_no_identity(webhook):
    client, _, worker = webhook
    assert (
        await client.post(
            WEBHOOK_PATH, json=update(), headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}
        )
    ).status_code == 403
    assert (await client.post(WEBHOOK_PATH, json={"update_id": 101})).status_code == 200
    assert await events(worker) == []
    async with worker.database.transaction() as session:
        assert list(await session.scalars(select(User))) == []


async def test_real_gateway_readiness_includes_database_and_redis(webhook):
    client, publisher, _ = webhook
    assert (await client.get("/readyz")).json() == {
        "status": "ready",
        "checks": {"database": True, "redis": True},
    }
    with patch.object(publisher.client, "ping", side_effect=RuntimeError("synthetic unavailable")):
        response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": True, "redis": False}
    assert (await client.get("/healthz")).status_code == 200
