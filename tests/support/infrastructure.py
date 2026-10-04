"""Each run owns an isolated Compose project, ports and database volume."""

import os
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from oria_engine.config import Settings
from oria_engine.db.session import Database

ROOT = Path(__file__).resolve().parents[2]


def migrate(url, *args):
    env = os.environ.copy()
    for name in Settings.model_fields:
        env.pop(name.upper(), None)
        env.pop(name, None)
    env.update(APP_ENV="test", DATABASE_URL=url)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), *args],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, "Migration command failed"


@pytest.fixture
async def database(infrastructure):
    db = Database(Settings(_env_file=None, database_url=infrastructure[0]))
    try:
        yield db
    finally:
        await db.close()


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
    for name in Settings.model_fields:
        env.pop(name.upper(), None)
        env.pop(name, None)
    env["POSTGRES_PASSWORD"] = secrets.token_hex(24)
    project = f"oria-test-{uuid.uuid4().hex[:12]}"
    command = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        project,
        "-f",
        str(ROOT / "deploy/compose.test.yaml"),
    ]

    def compose(*args, timeout=180):
        try:
            result = subprocess.run(
                [*command, *args], env=env, capture_output=True, text=True, timeout=timeout
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
        compose("up", "-d", "--wait", "--wait-timeout", "90", "postgres", "redis")
        pg_port = compose("port", "postgres", "5432").rsplit(":", 1)[1]
        redis_port = compose("port", "redis", "6379").rsplit(":", 1)[1]
        yield (
            f"postgresql+psycopg://oria:{env['POSTGRES_PASSWORD']}@127.0.0.1:{pg_port}/oria",
            f"redis://127.0.0.1:{redis_port}/0",
            compose,
        )
    finally:
        compose("down", "--volumes", "--remove-orphans")


@pytest.fixture(scope="session")
def astrology_container(infrastructure):
    compose = infrastructure[2]
    compose("--profile", "astrology", "build", "astrology-mcp", timeout=1800)
    compose("--profile", "astrology", "up", "-d", "--wait", "--wait-timeout", "90", "astrology-mcp")
    address = compose("port", "astrology-mcp", "8000")
    assert address.startswith("127.0.0.1:")
    return f"http://{address}/mcp"
