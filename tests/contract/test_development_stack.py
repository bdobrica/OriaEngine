"""Start the documented Compose overlay without operator secrets or provider calls."""

import base64
import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx

from oria_engine.config import Settings


def test_development_stack(tmp_path):
    root = Path(__file__).resolve().parents[2]
    project = f"oria-dev-test-{uuid4().hex[:12]}"
    env = os.environ.copy()
    for name in Settings.model_fields:
        env.pop(name.upper(), None)
        env.pop(name, None)
    env.update(
        POSTGRES_PASSWORD=secrets.token_hex(24),
        POSTGRES_PASSWORD_URLENCODED="",
        POSTGRES_PORT="0",
        REDIS_PORT="0",
        GATEWAY_PORT="0",
        TELEGRAM_BOT_TOKEN="123456:" + secrets.token_hex(24),
        TELEGRAM_WEBHOOK_SECRET=secrets.token_hex(24),
        PROFILE_ENCRYPTION_KEY=base64.b64encode(secrets.token_bytes(32)).decode(),
        ORIA_APP_IMAGE="oria-engine:development-test",
        # Deliberately unavailable: startup/probes must not call an external provider.
        SECOND_CONTEXT_DOCKER_URL="http://127.0.0.1:9",
    )
    command = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        project,
        "-f",
        str(root / "deploy/compose.yaml"),
        "-f",
        str(root / "deploy/compose.dev.yaml"),
        "--profile",
        "dev",
        "--profile",
        "astrology",
    ]

    def compose(*args, timeout=180):
        result = subprocess.run(
            [*command, *args],
            env=env,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        assert result.returncode == 0, "Isolated development Compose command failed"
        return result.stdout.strip()

    def execute(service, code):
        return compose("exec", "-T", service, "python", "-c", code)

    try:
        config = json.loads(compose("config", "--format", "json"))["services"]
        assert set(config) == {"postgres", "redis", "astrology-mcp", "migrate", "gateway", "worker"}
        for service in ("gateway", "worker"):
            assert (
                config[service]["depends_on"]["migrate"]["condition"]
                == "service_completed_successfully"
            )
            assert (
                config[service]["environment"]["SECOND_CONTEXT_BASE_URL"]
                == env["SECOND_CONTEXT_DOCKER_URL"]
            )
        assert config["gateway"]["image"] == config["worker"]["image"] == config["migrate"]["image"]
        assert "ports" not in config["worker"] and "ports" not in config["astrology-mcp"]
        assert (
            not {"TELEGRAM_BOT_TOKEN", "PROFILE_ENCRYPTION_KEY"}
            & config["migrate"]["environment"].keys()
        )
        assert "environment" not in config["astrology-mcp"]
        compose("build", timeout=1800)
        compose("up", "-d", "--wait", "--wait-timeout", "120")
        for service in ("gateway", "worker", "astrology-mcp"):
            identifier = compose("ps", "-q", service)
            details = json.loads(
                subprocess.check_output(["docker", "inspect", identifier], text=True)
            )[0]
            assert details["State"]["Health"]["Status"] == "healthy"
            assert details["HostConfig"]["ReadonlyRootfs"]
            assert details["Config"]["User"] == "65532:65532"
            assert details["HostConfig"]["CapDrop"] == ["ALL"]
        assert (
            execute(
                "gateway",
                "from importlib.util import find_spec; assert find_spec('pytest') is None",
            )
            == ""
        )
        assert (
            execute("gateway", "from pathlib import Path; assert not Path('/app/.env').exists()")
            == ""
        )
        schema = compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "oria",
            "-d",
            "oria",
            "-Atc",
            "SELECT version_num FROM alembic_version",
        )
        assert schema == "0008"
        address = compose("port", "gateway", "8001")
        assert address.startswith("127.0.0.1:")
        with httpx.Client(base_url=f"http://{address}", trust_env=False, timeout=5) as client:
            assert client.get("/readyz").json() == {
                "status": "ready",
                "checks": {"database": True, "redis": True},
            }
            assert client.post("/telegram/webhook", json={}).status_code == 403
        execute(
            "worker", "from pathlib import Path; assert Path('/tmp/oria-worker.health').exists()"
        )
        # Exercise failed probes without changing the running application's configuration.
        for options in (
            ["-e", "DATABASE_URL=postgresql+psycopg://oria:synthetic@127.0.0.1:9/oria"],
            ["-e", "REDIS_URL=redis://127.0.0.1:9/0"],
        ):
            result = subprocess.run(
                [
                    *command,
                    "exec",
                    "-T",
                    *options,
                    "worker",
                    "python",
                    "-m",
                    "oria_engine.container_health",
                    "worker",
                ],
                env=env,
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert result.returncode == 1
            assert result.stdout == result.stderr == ""
        execute(
            "worker",
            "import os; from pathlib import Path; "
            "p=Path('/tmp/stale.health'); p.touch(); os.utime(p,(0,0))",
        )
        result = subprocess.run(
            [
                *command,
                "exec",
                "-T",
                "worker",
                "python",
                "-m",
                "oria_engine.container_health",
                "worker",
                "--health-file",
                "/tmp/stale.health",
            ],
            env=env,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 1
        assert result.stdout == result.stderr == ""
        # A UUID without a canonical row exercises the real actor without sending to Telegram.
        job_id = str(uuid4())
        execute(
            "gateway",
            "from oria_engine.config import load_settings; "
            "from oria_engine.queue.broker import Publisher; "
            f"p=Publisher(load_settings()); p.send('{job_id}'); p.close()",
        )
        deadline = time.monotonic() + 15
        while f'"job_id": "{job_id}"' not in compose("logs", "worker"):
            assert time.monotonic() < deadline, "Worker did not consume its UUID job"
            time.sleep(0.2)
        # Same application image executes a real MCP calculation over the private network.
        execute(
            "worker",
            "import asyncio; from oria_engine.config import load_settings; "
            "from oria_engine.astrology.client import FastMCPAstrologyClient; "
            "from oria_engine.astrology.contracts import NatalRequest; "
            "r=asyncio.run(FastMCPAstrologyClient(load_settings().astrology_mcp_url).calculate_natal_chart("
            "NatalRequest.model_validate({'birth_time_accuracy':'unknown','local_birth_date':'2000-01-01',"
            "'latitude':51.5,'longitude':0}))); assert not r.planets",
        )
        # Reapplying the normal workflow repeats migrations safely and preserves the volume.
        compose("down", "--remove-orphans")
        compose("up", "-d", "--wait", "--wait-timeout", "120")
        assert (
            compose(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "oria",
                "-d",
                "oria",
                "-Atc",
                "SELECT version_num FROM alembic_version",
            )
            == schema
        )
        logs = compose("logs", "gateway", "worker", "migrate", "astrology-mcp")
        assert all(
            env[name] not in logs
            for name in (
                "TELEGRAM_BOT_TOKEN",
                "TELEGRAM_WEBHOOK_SECRET",
                "PROFILE_ENCRYPTION_KEY",
                "POSTGRES_PASSWORD",
            )
        )
        assert "2000-01-01" not in logs
    finally:
        compose("down", "--volumes", "--remove-orphans")
