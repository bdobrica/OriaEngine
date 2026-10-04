"""Fixture replay with observable wire replies and explicit Redis dispatch."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from oria_engine.db.models import InboundEvent
from oria_engine.telegram.webhook import WEBHOOK_PATH

FIXTURES = Path(__file__).resolve().parents[1] / "e2e/fixtures"


def scenario_steps(scenario):
    return json.loads((FIXTURES / f"{scenario}.json").read_text())


class Replay:
    def __init__(self, client, publisher, worker, telegram, context):
        self.client = client
        self.publisher = publisher
        self.worker = worker
        self.telegram = telegram
        self.context = context
        self.consumer = publisher.broker.consume("inbound", timeout=100)
        self.sequence = 100
        self.last_update = None

    def update(self, *, text=None, button=None, user=42):
        self.sequence += 1
        inbound = json.loads(
            (FIXTURES / ("callback.json" if button else "message.json")).read_text()
        )
        inbound["update_id"] = self.sequence
        message = inbound.get("message", inbound.get("callback_query", {}).get("message"))
        message["chat"]["id"] = user
        message["message_id"] = self.sequence
        if button:
            buttons = [
                b
                for row in self.telegram.messages[-1]["reply_markup"]["inline_keyboard"]
                for b in row
            ]
            matches = [b for b in buttons if button in b["text"]]
            assert len(matches) == 1, "Replay button must select exactly one current action"
            inbound["callback_query"]["data"] = matches[0]["callback_data"]
            inbound["callback_query"]["from"]["id"] = user
        else:
            message["from"]["id"] = user
            message["text"] = text
            if text.startswith("/"):
                message["entities"] = [
                    {"type": "bot_command", "offset": 0, "length": len(text.split()[0])}
                ]
        return inbound

    async def post(self, inbound):
        response = await self.client.post(WEBHOOK_PATH, json=inbound)
        assert response.status_code == 200
        if "callback_query" in inbound:
            assert response.json()["method"] == "answerCallbackQuery"
            assert response.json()["callback_query_id"] == inbound["callback_query"]["id"]
        else:
            assert response.json() == {"ok": True}

    async def dispatch(self):
        async with asyncio.timeout(5):
            while (job := await asyncio.to_thread(next, self.consumer)) is None:
                await asyncio.sleep(0.01)
        assert job.actor_name == "process_inbound" and job.kwargs == {}
        assert len(job.args) == 1 and str(UUID(job.args[0])) == job.args[0]
        identifier = UUID(job.args[0])
        await self.worker.process(identifier)
        self.consumer.ack(job)
        return identifier

    async def send(self, *, text=None, button=None, contains=None, user=42, delivered=True):
        inbound = self.update(text=text, button=button, user=user)
        before = len(self.telegram.messages)
        await self.post(inbound)
        identifier = await self.dispatch()
        async with self.worker.database.transaction() as session:
            event = await session.get(InboundEvent, identifier)
            assert event.provider_update_id == str(inbound["update_id"])
            assert event.status == ("sent" if delivered else "dead")
            if not delivered:
                assert event.failure_code == "user_unavailable"
            assert event.encrypted_input is None and event.encrypted_reply is None
        assert len(self.telegram.messages) == before + int(delivered)
        self.last_update = deepcopy(inbound)
        if not delivered:
            assert contains is None
            return None
        reply = self.telegram.messages[-1]
        assert reply["chat_id"] == str(user)
        assert not reply.get("parse_mode")
        if contains:
            assert contains in reply["text"]
        return reply

    async def run(self, scenario):
        for step in scenario_steps(scenario):
            await self.send(**step)

    async def no_job(self):
        assert await asyncio.to_thread(next, self.consumer) is None

    async def user_id(self, user=42):
        from oria_engine.db.models import SocialIdentity

        async with self.worker.database.transaction() as session:
            return await session.scalar(
                select(SocialIdentity.user_id).where(
                    SocialIdentity.provider == "telegram",
                    SocialIdentity.provider_user_id == str(user),
                )
            )
