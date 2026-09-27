"""Each run owns an isolated Compose project, ports and database volume."""

import os
import secrets
import subprocess
import uuid
from pathlib import Path

import pytest

from oria_engine.config import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture(scope="session")
def infrastructure():
    env = os.environ.copy()
    env.update(
        POSTGRES_PASSWORD=secrets.token_hex(24),
        POSTGRES_PORT="0",
        REDIS_PORT="0",
    )
    project = f"oria-test-{uuid.uuid4().hex[:12]}"
    command = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        project,
        "-f",
        str(ROOT / "deploy/compose.yaml"),
    ]

    def compose(*args):
        try:
            result = subprocess.run(
                [*command, *args], env=env, capture_output=True, text=True, timeout=180
            )
        except (OSError, subprocess.TimeoutExpired):
            pytest.fail(
                "Compose unavailable or timed out; check Docker and pre-pull service images",
                pytrace=False,
            )
        if result.returncode:
            pytest.fail("Isolated Compose command failed; check Docker availability", pytrace=False)
        return result.stdout.strip()

    try:
        compose("up", "-d", "--wait", "--wait-timeout", "90")
        pg_port = compose("port", "postgres", "5432").rsplit(":", 1)[1]
        redis_port = compose("port", "redis", "6379").rsplit(":", 1)[1]
        yield (
            f"postgresql+psycopg://oria:{env['POSTGRES_PASSWORD']}@127.0.0.1:{pg_port}/oria",
            f"redis://127.0.0.1:{redis_port}/0",
            compose,
        )
    finally:
        compose("down", "--volumes", "--remove-orphans")
