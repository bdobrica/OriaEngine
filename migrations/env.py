"""Use the same settings and async psycopg driver as the application."""

import asyncio

from alembic import context
from alembic.util import CommandError
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from oria_engine.config import load_settings
from oria_engine.db import models  # noqa: F401 -- register domain metadata for autogeneration
from oria_engine.db.session import Base
from oria_engine.observability import configure_logging


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_online(url: str) -> None:
    engine = create_async_engine(
        url, poolclass=pool.NullPool, hide_parameters=True, connect_args={"connect_timeout": 5}
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


try:
    settings = load_settings()
    configure_logging(settings)
    if context.is_offline_mode():
        context.configure(
            url=settings.database_url.get_secret_value(),
            target_metadata=Base.metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        asyncio.run(run_online(settings.database_url.get_secret_value()))
except Exception:
    # Driver errors can contain SQL, data and credentials; never print a traceback.
    raise CommandError("Migration failed; check configuration and database availability") from None
