"""Stateful HTTP contract stub, not a replacement for upstream integration tests."""

import json
from uuid import uuid4

import httpx


class SecondContextStub:
    def __init__(self, *, token=None, subject=None, namespace=None):
        self.token = token
        self.subject = subject
        self.namespace = namespace
        self.purged = set()
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
        if self.namespace and (
            not user.startswith(self.namespace + ":")
            or request.headers.get("X-SecondContext-Subject") != user
        ):
            return httpx.Response(403)
        if request.url.path.endswith("/v1/subjects/purge"):
            self.purged.add(user)
            self.memories.pop(user, None)
            self.sessions = {key: owner for key, owner in self.sessions.items() if owner != user}
            return httpx.Response(
                200, json={"contract_version": 1, "user": user, "status": "completed"}
            )
        if user in self.purged:
            return httpx.Response(410)
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
