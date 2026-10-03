# Local infrastructure and migrations

Run `make env`, replace the local password placeholder in both
`POSTGRES_PASSWORD` and `DATABASE_URL`, then:

```sh
make infra-up
make migrate
```

Compose starts PostgreSQL 16 and Redis 7 and waits for both health checks.
The fixed local project is `oria-local`. Ports bind only to loopback, defaulting
to 5432 and 6379. If these ports are occupied, set `POSTGRES_PORT` and
`REDIS_PORT` in `.env` and update the corresponding application URLs.
Percent-encode special characters in the password portion of `DATABASE_URL`.
Compose receives only its database settings, not Telegram or encryption secrets.
These services are for local development, not production deployment.

PostgreSQL uses a named volume; `make infra-down` removes containers but retains
canonical data. Redis persistence is disabled: restarting it loses coordination
state. No consent/profile data belongs in Redis.

`make infra-reset` stops the local stack and **deletes its PostgreSQL volume**.
It is limited to `APP_ENV=development` or `test`, including values read from
`.env`. Run `make infra-up migrate` afterward to recreate the empty database.
Do not use this workflow against valuable data. Changing the password in `.env`
does not change credentials inside an existing PostgreSQL volume.

## Migration workflow

Alembic reads `DATABASE_URL` through application settings. It uses async psycopg,
transactional PostgreSQL DDL, and a short-lived connection without a pool.
The URL is never stored in `alembic.ini`. Production settings validation still
applies. Migrations are explicit operator commands, not automatic HTTP startup
side effects; run one migration process at a time.

`make migrate` upgrades to head and is safe to repeat. The initial revision
`0001` establishes the Alembic version baseline without domain tables.
Revision `0002` adds the identity and consent tables described in
[Identity and consent](identity-consent.md).
Revision `0003` adds [encrypted birth profiles](birth-profiles.md).
Revision `0004` adds [encrypted onboarding drafts](onboarding.md).
Revision `0005` adds [derived astrology profiles](astrology-profiles.md).
Revision `0006` adds [durable inbound events](worker-queue.md). Its downgrade drops
queued work and deduplication history but preserves consent, drafts and profiles.
Revision `0007` adds [conversation session mappings](second-context.md); its
downgrade removes only local mappings and does not purge remote SecondContext data.
Revision `0008` adds [durable deletion jobs](deletion.md) and unlinked inbound receipts.
Its development downgrade drops deletion progress and unlinked receipts; it cannot
restore deleted users or remote context. Do not downgrade with active deletion jobs.
`make migrate-down` rolls back one revision and is guarded to development/test.
It uses the configured database URL: verify that URL points to your intended
development database before running it. Downgrading `0002` drops all identity
and consent data.

For a new schema change, import the affected models in `migrations/env.py`,
then generate and review a revision:

```sh
uv run alembic revision --autogenerate -m "Describe the schema change"
make format
make migrate
uv run alembic check
make verify
```

Review generated SQL and downgrade behavior; do not modify previously applied
revisions. Do not use `Base.metadata.create_all()` in application startup.
Migration failures emit a generic diagnostic to avoid exposing driver errors
containing SQL or data. Never add profile values or credentials to migrations.

## Sessions and repositories

`oria_engine.db.session.Base` owns OriaEngine model metadata and stable constraint
names. Create one `Database(settings)` per process/event-loop lifetime and call
`await database.close()` after in-flight work has drained. The HTTP skeleton
does not use storage yet; the consuming stage will register that lifecycle
resource and its readiness check.

```python
async with database.transaction() as session:
    # Pass this session to repositories participating in one operation.
    ...
```

The helper commits on success, rolls back on exception or cancellation, and
closes the session. Separate operations/tasks get separate sessions.
Repositories accept an existing `AsyncSession`; they may flush but do not commit,
close sessions, or commit independent transactions. Identity creation uses a
savepoint to recover a uniqueness race without discarding caller work; the outer
transaction still owns both rows. The application operation owns the transaction
boundary. User-owned queries require an explicit internal user UUID
and a user predicate; no generic unscoped CRUD repository is provided.
The sole pre-UUID lookup is trusted transport identity resolution; see
[repository boundaries](identity-consent.md). Use only the OriaEngine database,
never another component's tables.

SQL echo is disabled and SQLAlchemy hides bound parameters in its diagnostics.
This does not make driver exceptions safe to log: retain the application logging
boundary and never log exception strings or raw payloads.

## Verification

`make test-integration` starts the same service definitions in a unique temporary
Compose project with random credentials and ports, ignoring developer `.env`
and service URLs. It removes only that project's containers and volumes afterward.
Docker/Compose are required; unavailable Docker fails the lane rather than skipping it.
An interrupted test process may leave an `oria-test-*` project for manual cleanup.

Tests cover empty/repeated upgrades, downgrade/re-upgrade, metadata drift,
transaction commit/rollback/cancellation, independent concurrent sessions, and
Redis loss without PostgreSQL data loss. `make verify` includes this lane in local
development and CI. No live Telegram or SecondContext credentials are required.

The async migration setup follows the
[Alembic asyncio recipe](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic).
