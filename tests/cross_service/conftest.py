"""Real owning gateway over HTTP; never inspect or mutate its database from Oria."""

import asyncio
import json
import os
import secrets
import subprocess
from pathlib import Path
from socket import socket
from uuid import uuid4

import httpx
import pytest
from aiohttp import web

from oria_engine.config import Settings
from oria_engine.context.projections import LinkedContext, recover_projections
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.context.service import ConversationContext
from tests.integration.test_astrology_profiles import confirm
from tests.integration.test_conversation_worker import conversation as conversation
from tests.integration.test_onboarding import owner
from tests.integration.test_queue import queue as queue
from tests.support.http_fakes import serve
from tests.support.infrastructure import ROOT
from tests.support.infrastructure import database as database
from tests.support.infrastructure import infrastructure as infrastructure
from tests.support.infrastructure import isolated_settings as isolated_settings


def checked(command, *, env, cwd=ROOT, timeout=180):
    result = subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
    )
    # Never print connection strings or service credentials on process failure.
    if result.returncode:
        diagnostic = result.stderr
        for key, value in env.items():
            if any(word in key for word in ("PASSWORD", "TOKEN", "KEY", "DSN")) and value:
                diagnostic = diagnostic.replace(value, "[redacted]")
                if "=" in value:
                    diagnostic = diagnostic.replace(value.rsplit("=", 1)[-1], "[redacted]")
        pytest.fail(f"{Path(command[0]).name} failed: {diagnostic[:2000]}", pytrace=False)
    return result.stdout.strip()


@pytest.fixture(scope="session")
def gateway_install(tmp_path_factory):
    source = os.environ.get("SECOND_CONTEXT_SOURCE")
    assert source, "Set SECOND_CONTEXT_SOURCE to a CH3-capable SecondContext checkout"
    source = Path(source).resolve()
    assert (source / "cmd/api/main.go").is_file(), "Invalid SecondContext source checkout"
    directory = tmp_path_factory.mktemp("history-gateway")
    # No inherited runtime settings, credentials, .env, or live endpoints.
    env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    for name in ("api", "migrate"):
        checked(["go", "build", "-o", str(directory / name), f"./cmd/{name}"], env=env, cwd=source)
    checked(
        ["python3", "scripts/sync_history_contract.py", "--source", str(source), "--check"],
        env=env,
    )
    env["POSTGRES_PASSWORD"] = secrets.token_hex(24)
    command = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        f"oria-history-test-{uuid4().hex[:12]}",
        "-f",
        str(ROOT / "deploy/compose.history-test.yaml"),
    ]

    def compose(*args):
        return checked([*command, *args], env=env)

    try:
        compose("up", "-d", "--wait", "--wait-timeout", "90")
        pg_port = compose("port", "postgres", "5432").rsplit(":", 1)[1]
        vector_port = compose("port", "qdrant", "6333").rsplit(":", 1)[1]
        env.update(
            APP_ENV="test",
            POSTGRES_ENABLED="true",
            POSTGRES_HOST="127.0.0.1",
            POSTGRES_PORT=pg_port,
            POSTGRES_USER="secondcontext",
            POSTGRES_DB="secondcontext",
            POSTGRES_SSLMODE="disable",
            QDRANT_URL=f"http://127.0.0.1:{vector_port}",
            QDRANT_VECTOR_SIZE="3",
            AUTH_ENABLED="true",
            AUTH_SERVICE_TOKENS=f"oria:={secrets.token_hex(24)}",
            HISTORY_ENABLED="true",
            KNOWLEDGE_ENABLED="false",
            HTTP_RATE_LIMIT_REQUESTS_PER_MINUTE="10000",
            LOG_LEVEL="error",
            OPENAI_CHAT_MODEL="synthetic-model",
            OPENAI_API_KEY=secrets.token_hex(24),
        )
        # Only the provider's own executable applies its migrations.
        checked([str(directory / "migrate"), "up"], env=env, cwd=source)
        yield directory / "api", env
    finally:
        compose("down", "--volumes", "--remove-orphans")


class ModelRecorder:
    def __init__(self):
        self.calls = []
        self.reply = "First, take a walk. Second, write a short reflection."
        self.recall_code = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.app = web.Application()
        self.app.router.add_post("/v1/chat/completions", self.chat)
        self.app.router.add_post("/v1/embeddings", self.embed)

    async def chat(self, request):
        self.calls.append(await request.json())
        self.entered.set()
        await self.release.wait()
        reply = self.reply
        if self.recall_code:
            codes = [
                m["content"].removeprefix("Synthetic code: ")
                for m in self.calls[-1]["messages"]
                if m["role"] == "assistant" and m["content"].startswith("Synthetic code: ")
            ]
            reply = codes[-1] if codes else "No code in the actual model input"
        return web.json_response(
            {
                "id": "synthetic-upstream-id",
                "object": "chat.completion",
                "created": 1780000000,
                "model": "synthetic-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": reply},
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
            }
        )

    async def embed(self, request):
        await request.read()
        return web.json_response({"data": [{"index": 0, "embedding": [1.0, 0.0, 0.0]}]})


class WireRecorder(httpx.AsyncBaseTransport):
    """Forward real HTTP; inject failure only before a call or after its real response."""

    def __init__(self):
        self.transport = httpx.AsyncHTTPTransport()
        self.calls = []
        self.lose = set()
        self.block = set()
        self.statuses = []

    async def handle_async_request(self, request):
        body = json.loads(request.content)
        self.calls.append((request.url.path, body))
        if request.url.path in self.block:
            return httpx.Response(503, json={"error": {"code": "history_unavailable"}})
        response = await self.transport.handle_async_request(request)
        await response.aread()
        code = response.json().get("error", {}).get("code") if response.is_error else None
        self.statuses.append((request.url.path, response.status_code, code))
        if request.url.path in self.lose:
            await response.aread()
            await response.aclose()
            raise httpx.ReadTimeout("Synthetic acknowledgement loss", request=request)
        return response

    async def aclose(self):
        await self.transport.aclose()

    def bodies(self, path):
        return [body for route, body in self.calls if route == path]


class Gateway:
    def __init__(self, binary, env):
        self.binary, self.env = binary, env
        self.process = None
        with socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.env["HTTP_ADDR"] = f"127.0.0.1:{port}"
        self.url = f"http://127.0.0.1:{port}"

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            str(self.binary),
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(100):
                assert self.process.returncode is None, "Synthetic gateway failed to start"
                try:
                    await client.get(self.url + "/health", timeout=0.2)
                    return
                except httpx.TransportError:
                    await asyncio.sleep(0.05)
        raise AssertionError("Synthetic gateway did not listen")

    async def stop(self):
        if self.process is not None and self.process.returncode is None:
            self.process.kill()  # Exercise recovery from process death, not just object recreation.
            await self.process.wait()

    async def restart(self):
        await self.stop()
        await self.start()


@pytest.fixture
async def real_history(conversation, gateway_install):
    ingress, worker, astrology, _ = conversation
    binary, base_env = gateway_install
    model, wire = ModelRecorder(), WireRecorder()
    token = secrets.token_hex(24)
    async with serve(model.app) as model_url:
        gateway = Gateway(
            binary,
            {
                **base_env,
                "OPENAI_BASE_URL": model_url + "/v1",
                "AUTH_SERVICE_TOKENS": f"oria:={token}",
            },
        )
        provider = SecondContextProvider(
            Settings(
                _env_file=None,
                second_context_base_url=gateway.url,
                second_context_subject_namespace="oria",
                second_context_bearer_token=token,
                second_context_knowledge_enabled=True,
            ),
            transport=wire,
        )
        try:
            await gateway.start()
            worker.flow.onboarding.context = ConversationContext(
                provider, worker.flow.policy_version
            )
            worker.history_provider, worker.history_enabled = provider, True
            ingress.history_enabled = True
            await confirm(worker.flow)
            user_id = await owner(worker.database)
            async with worker.database.transaction() as session:
                linked = LinkedContext(
                    session, worker.encryption, worker.flow.policy_version, provider
                )
                await linked.stage(user_id)
            await recover_projections(
                worker.database, worker.encryption, worker.flow.policy_version, provider
            )
            # Capability is necessary, but subsequent tests prove generation/finalization too.
            await provider.history_capabilities(user_id)
            yield ingress, worker, model, wire, gateway, user_id
        finally:
            model.release.set()
            await provider.aclose()
            await gateway.stop()
