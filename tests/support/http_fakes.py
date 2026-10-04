"""Loopback HTTP fixtures exercising real clients, with no provider credentials."""

import json
from collections import defaultdict
from contextlib import asynccontextmanager
from socket import socket
from uuid import UUID

import httpx
from aiohttp import web

from tests.support.second_context import SecondContextStub


@asynccontextmanager
async def serve(app):
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    listener = socket()
    try:
        listener.bind(("127.0.0.1", 0))
        await web.SockSite(runner, listener).start()
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        await runner.cleanup()
        listener.close()


class TelegramFake:
    def __init__(self, token):
        self.token = token
        self.messages = []
        self.fail_sends = False
        self.app = web.Application()
        self.app.router.add_post("/bot{token}/{method}", self.handle)

    async def handle(self, request):
        if request.match_info["token"] != self.token:
            return web.json_response({"ok": False, "error_code": 401}, status=401)
        bot = {"id": 123456, "is_bot": True, "first_name": "Synthetic", "username": "oria_test_bot"}
        if request.match_info["method"] == "getMe":
            return web.json_response({"ok": True, "result": bot})
        if request.match_info["method"] != "sendMessage":
            return web.json_response({"ok": False, "error_code": 404}, status=404)
        body = dict(await request.post())
        if self.fail_sends:
            return web.json_response(
                {"ok": False, "error_code": 500, "description": "Synthetic send failure"},
                status=500,
            )
        if "reply_markup" in body:
            body["reply_markup"] = json.loads(body["reply_markup"])
        self.messages.append(body)
        return web.json_response(
            {
                "ok": True,
                "result": {
                    "message_id": len(self.messages),
                    "date": 946684800,
                    "chat": {"id": int(body["chat_id"]), "type": "private"},
                    "from": bot,
                    "text": body["text"],
                },
            }
        )


class SecondContextFake:
    def __init__(self, token):
        self.stub = SecondContextStub(token=token, namespace="oria")
        self.transcripts = defaultdict(list)
        self.draft = "A synthetic reflection based on the supplied facts."
        self.fail_responses = False
        self.app = web.Application()
        for route in ("/v1/responses", "/memory/ingest", "/v1/subjects/purge"):
            self.app.router.add_post(route, self.handle)

    async def handle(self, request):
        content = await request.read()
        body = json.loads(content)
        # The fixture implements only the versioned public subject boundary.
        try:
            subject = body["user"]
            canonical = f"oria:{UUID(subject.removeprefix('oria:'))}"
        except (ValueError, KeyError):
            return web.json_response({}, status=403)
        if canonical != subject:
            return web.json_response({}, status=403)
        if request.path == "/v1/responses" and self.fail_responses:
            return web.json_response({}, status=503)
        result = self.stub(
            httpx.Request(
                "POST", f"http://fixture{request.path}", headers=request.headers, content=content
            )
        )
        if result.status_code >= 400:
            return web.json_response({}, status=result.status_code)
        response = result.json()
        if request.path == "/v1/responses":
            response["output_text"] = self.draft
            self.transcripts[subject].append((body["input"], self.draft))
        elif request.path == "/v1/subjects/purge":
            self.transcripts.pop(subject, None)
        return web.json_response(response, status=result.status_code)
