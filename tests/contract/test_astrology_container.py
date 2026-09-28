"""Real private-network HTTP MCP smoke test; isolated from developer services."""

import asyncio
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

from oria_engine.astrology.client import FastMCPAstrologyClient
from oria_engine.astrology.contracts import NatalRequest


def test_astrology_container():
    root = Path(__file__).resolve().parents[2]
    project = f"oria-mcp-test-{uuid4().hex[:12]}"
    env = {**os.environ, "POSTGRES_PASSWORD": "unused-synthetic-compose-value"}
    command = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        project,
        "-f",
        str(root / "deploy/compose.yaml"),
        "--profile",
        "astrology",
    ]

    def compose(*args, timeout=180):
        result = subprocess.run(
            [*command, *args], env=env, capture_output=True, text=True, timeout=timeout
        )
        assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
        return result.stdout

    try:
        compose("build", "astrology-mcp", timeout=1800)
        compose("up", "-d", "--wait", "--wait-timeout", "90", "astrology-mcp")
        container = compose("ps", "-q", "astrology-mcp").strip()
        details = json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[
            0
        ]
        assert not details["HostConfig"]["PortBindings"]
        assert details["HostConfig"]["ReadonlyRootfs"]
        assert details["Config"]["User"] == "65532:65532"
        compose("exec", "-T", "astrology-mcp", "python", "-m", "oria_engine.astrology.smoke")
        # The explicit polling override remains loopback-only and is reachable from the host.
        command[command.index("--profile") : command.index("--profile")] = [
            "-f",
            str(root / "deploy/compose.polling.yaml"),
        ]
        env["ASTROLOGY_MCP_PORT"] = "0"
        compose("up", "-d", "--wait", "--wait-timeout", "90", "astrology-mcp")
        address = compose("port", "astrology-mcp", "8000").strip()
        assert address.startswith("127.0.0.1:")
        client = FastMCPAstrologyClient(f"http://{address}/mcp")
        result = asyncio.run(
            client.calculate_natal_chart(
                NatalRequest.model_validate(
                    {
                        "birth_time_accuracy": "unknown",
                        "local_birth_date": "2000-01-01",
                        "latitude": 51.5,
                        "longitude": 0,
                    }
                )
            )
        )
        assert not result.planets
        logs = compose("logs", "astrology-mcp")
        assert "2000-01-01" not in logs and "51.5" not in logs
    finally:
        compose("down", "--volumes", "--remove-orphans")
