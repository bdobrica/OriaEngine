# Stage 12 adapter foundation — 2026-09-28

## Scope

Implemented a typed context-provider interface, SecondContext HTTP adapter,
consent-fenced application service, stable per-user session mapping, generated
migration `0007`, and reusable synthetic HTTP stub. No new dependencies or existing
Astrology MCP contract changes. No Telegram/worker wiring or new external storage
has been enabled.

Inspected the local SecondContext checkout at commit
`b7f117f428ac9bebfc8019bb6c63d7a43bde61d4`, including its documented auth behavior
and HTTP handlers. No upstream files were changed. The consumer contract is
[versioned separately](../../contracts/second-context/v1.md).

## Verification

- Generated migration `0007` with Alembic autogenerate against isolated temporary
  PostgreSQL; inspected the resulting owner FK, unique session ID, primary key,
  timestamp and downgrade.
- Focused adapter, session and migration suite: **31 passed**. It covers scoped
  synthetic continuity, optional/subject-bound auth, session reuse and concurrent
  creation, caller rollback, consent withdrawal fencing, deleted/missing users,
  malformed/wrong-scope/oversized responses, HTTP errors, redirects, safe retries,
  deadlines, cancellation and explicit unsupported purge.
- Full `make verify`: **passed** — formatting/lint, strict mypy (44 source
  files), 167 unit tests, 63 integration tests and 51 contract tests: **281 total**.
  Integration used isolated PostgreSQL/Redis, and the contract lane included the
  real Astrology MCP container. All services were cleaned up by the test fixtures.

An initial contract-test collection failed because the shared test stub was not
importable as `tests.support`; adding the test package marker resolved it before
the focused run. The full working-tree whitespace check reports pre-existing
LICENSE line-ending changes; the Stage 12 diff passes separately. Existing LICENSE
and `.venv` changes are excluded from this implementation.

## Remaining acceptance criteria

Stage 12 is **not complete**. The inspected upstream has no subject-wide purge
endpoint; deleting individual memory items leaves messages/sessions and other
subject data. `purge()` therefore raises `PurgeUnsupported` without claiming
success. Its required semantics are documented, but successful purge/recovery
cannot be tested until the owning service implements them.

The configured bearer token is bound to one upstream subject; it cannot authorize
all Oria UUIDs. Multi-user service authentication requires an explicit upstream
security decision, preserving existing subject isolation. The proposed upstream
scope was raised with the user; no authority expansion was implemented.

Continuity tests use a synthetic HTTP stub; no deployed SecondContext service,
embedding provider or live LLM was exercised. No live Telegram calls, operator
schema migration, secret changes, remote deployment or upstream repository writes
were performed. Upstream response/ingest endpoints do not support idempotency keys;
an outer retry after an ambiguous write can duplicate remote state. Stage 16 must
account for this before claiming exactly-once context effects. The existing two
Starlette/AnyIO deprecation warnings are unrelated to this change.
