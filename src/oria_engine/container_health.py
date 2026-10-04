"""Private container probes; no payloads, provider calls or diagnostic output."""

import argparse
import asyncio
import time
import urllib.request
from collections.abc import Awaitable
from pathlib import Path
from typing import cast

from redis.asyncio import Redis
from sqlalchemy import text

from oria_engine.config import load_settings
from oria_engine.db.session import Database


async def worker_ready(health_file: Path) -> bool:
    if not 0 <= time.time() - health_file.stat().st_mtime <= 90:
        return False
    settings = load_settings()
    database = Database(settings)
    redis = Redis.from_url(
        settings.redis_url.get_secret_value(), socket_timeout=2, socket_connect_timeout=2
    )
    try:
        async with asyncio.timeout(5):
            async with database.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return await cast(Awaitable[bool], redis.ping()) is True
    finally:
        await redis.aclose()
        await database.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("gateway", "worker"))
    parser.add_argument("--health-file", type=Path, default=Path("/tmp/oria-worker.health"))
    args = parser.parse_args(argv)
    try:
        if args.role == "gateway":
            # Never send loopback health checks through an ambient proxy.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open("http://127.0.0.1:8001/readyz", timeout=5) as response:
                healthy = response.status == 200
        else:
            healthy = asyncio.run(worker_ready(args.health_file))
    except Exception:
        healthy = False
    raise SystemExit(0 if healthy else 1)


if __name__ == "__main__":
    main()
