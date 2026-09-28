"""Stateful HTTP contract stub, not a replacement for upstream integration tests."""

import json
from uuid import uuid4

import httpx


class SecondContextStub:
    def __init__(self, *, token=None, subject=None):
        self.token = token
        self.subject = subject
        self.sessions = {}
        self.memories = {}
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if self.token and request.headers.get("Authorization") != f"Bearer {self.token}":
            return httpx.Response(401)
        body = json.loads(request.content)
        user = body["user"]
        if self.subject and self.subject != user:
            return httpx.Response(400, json={"error": {"code": "identity_conflict"}})
        session = body["metadata"]["session_id"]
        if session in self.sessions and self.sessions[session] != user:
            return httpx.Response(404)
        self.sessions[session] = user
        if request.url.path.endswith("/memory/ingest"):
            self.memories.setdefault(user, []).append(body["summary"])
            return httpx.Response(
                201,
                json={
                    "id": str(uuid4()),
                    "user_id": str(uuid4()),
                    "summary": body["summary"],
                    "source": body["source"],
                },
            )
        if request.url.path.endswith("/v1/responses"):
            return httpx.Response(
                200,
                json={
                    "id": "resp_synthetic",
                    "object": "response",
                    "status": "completed",
                    "output_text": " ".join(self.memories.get(user, [])) or "No prior preference.",
                    "metadata": {
                        "session_id": session,
                        "context_packet": {"user_external_id": user},
                    },
                },
            )
        return httpx.Response(404)
