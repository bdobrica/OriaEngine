import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from redis.asyncio import Redis
from sqlalchemy import text

from oria_engine.config import Settings
from oria_engine.db.session import Database

from .conftest import ROOT


def migrate(url, *args):
    env = os.environ.copy()
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


async def test_migrations_empty_repeat_downgrade_and_metadata(database, infrastructure):
    url = infrastructure[0]
    migrate(url, "upgrade", "head")
    migrate(url, "upgrade", "head")
    async with database.transaction() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
    migrate(url, "check")
    migrate(url, "downgrade", "base")
    async with database.transaction() as session:
        assert await session.scalar(text("SELECT count(*) FROM alembic_version")) == 0
    migrate(url, "upgrade", "head")


async def test_transactions_commit_rollback_and_cancel(database):
    async with database.transaction() as session:
        await session.execute(text("CREATE TABLE transaction_probe (id integer PRIMARY KEY)"))
    try:
        async with database.transaction() as session:
            await session.execute(text("INSERT INTO transaction_probe VALUES (1)"))
        for error in (RuntimeError, asyncio.CancelledError):
            with pytest.raises(error):
                async with database.transaction() as session:
                    await session.execute(text("INSERT INTO transaction_probe VALUES (2)"))
                    raise error()
        async with database.transaction() as session:
            assert list(await session.scalars(text("SELECT id FROM transaction_probe"))) == [1]
    finally:
        async with database.transaction() as session:
            await session.execute(text("DROP TABLE transaction_probe"))


async def test_concurrent_operations_have_distinct_sessions(database):
    async def operation():
        async with database.transaction() as session:
            await session.execute(text("SELECT pg_sleep(0.05)"))
            return session

    first, second = await asyncio.gather(operation(), operation())
    assert first is not second


async def test_redis_loss_preserves_postgres(database, infrastructure):
    _, redis_url, compose = infrastructure
    async with database.transaction() as session:
        await session.execute(text("CREATE TABLE canonical_probe (id integer PRIMARY KEY)"))
        await session.execute(text("INSERT INTO canonical_probe VALUES (1)"))
    try:
        async with Redis.from_url(redis_url) as redis:
            assert await redis.ping()
            await redis.set("oria:test:disposable", "1")
        compose("restart", "redis")
        compose("up", "-d", "--wait", "--wait-timeout", "90")
        # Docker can assign a new ephemeral host port when a container restarts.
        redis_port = compose("port", "redis", "6379").rsplit(":", 1)[1]
        redis_url = f"redis://127.0.0.1:{redis_port}/0"
        async with Redis.from_url(redis_url) as redis:
            assert await redis.get("oria:test:disposable") is None
        async with database.transaction() as session:
            assert await session.scalar(text("SELECT id FROM canonical_probe")) == 1
    finally:
        async with database.transaction() as session:
            await session.execute(text("DROP TABLE canonical_probe"))
