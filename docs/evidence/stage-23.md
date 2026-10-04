# Stage 23 verification evidence

Date: 2026-10-04. Scope: Docker development orchestration, application image and
private container probes. Reference: [development guide](../development.md).

## Implemented and inspected

- Pinned multi-stage application image installs frozen runtime dependencies and
  the application wheel; gateway, worker and Alembic use the same image. The
  runtime contains migrations and bundled place data, without dev dependencies,
  build compilers, source/env bind mounts or operator credentials baked into layers.
- The existing Astrology MCP image and private internal network are reused.
- Development Compose overlays the existing local PostgreSQL/Redis definitions.
  PostgreSQL health precedes the one-shot migration job; successful migration
  gates gateway/worker, Redis gates both, and MCP readiness also gates the worker.
- Gateway publishes only on host loopback. Its launcher has an explicit container
  bind option while retaining loopback default and disabled access logs.
- Worker probes require a fresh, payload-free recovery heartbeat and bounded
  database/Redis connectivity. The optional marker is absent in the host workflow.
- Application containers run nonroot with read-only roots, bounded temporary
  storage, dropped capabilities and no privilege escalation. Migration receives
  only development mode/database configuration; MCP gets no integration secrets.
- External SecondContext URL/auth/namespace remain configurable through the
  existing versioned adapter. No cross-repository database access is introduced.
- `make dev`, `make down` and expanded `make logs` implement the local workflow;
  infrastructure stop/reset also recognize application containers. PostgreSQL data
  survives ordinary shutdown. The destructive reset retains its existing guard.

## Verification

`make format typecheck` passed: Ruff format/lint and strict mypy (60 source files).
Focused `uv run pytest tests/unit/test_container_health.py
tests/contract/test_development_stack.py --tb=short --show-capture=no`:
**10 passed** in 136.26 seconds.

The isolated development test builds the actual deployment images, starts all
owned services with generated credentials and random loopback ports, checks
migration head/readiness/container hardening, executes the real worker actor on
a UUID without a canonical row, and calls the private MCP service from the
application image. It verifies silent failed probes for unavailable DB/Redis and
a stale marker, checks secret/profile-value absence in application/MCP logs,
then stops/restarts with retained schema and removes its own containers/volume.
Unit checks cover loopback defaults, privacy logging, stale/future markers,
dependency probes, safe failure and heartbeat lifecycle/draining.

Full `make verify` passed (exit 0):

| Gate | Result |
| --- | --- |
| Ruff format/lint | 171 files passed format check; lint passed |
| Strict mypy | 60 source files passed |
| Unit | 380 passed, 36.54 seconds |
| Integration | 120 passed, 550.95 seconds |
| Contract | 93 passed, 128.03 seconds |
| E2E | 11 passed, 112.39 seconds |

Total: **604 tests passed**. The final contract lane exercised the worker's
150-second shutdown-grace configuration. Two existing Starlette/AnyIO deprecation
warnings occurred in the unit lane. Documentation links, Make command expansion
and final whitespace checks passed. The final diff was reviewed for unrelated
changes, generated-file drift, credentials and unintended contract changes.

The first focused container run also passed. A Redis stub annotation mismatch
found by strict mypy was corrected with the repository's existing awaitable cast
convention; no dependency or retry behavior was changed.

## Limits and final review

No live Telegram, model, upstream SecondContext/Qdrant, public TLS/proxy, provider
retention, backup or production deployment was exercised. The stack starts with
an unavailable synthetic context endpoint because provider availability is not
startup readiness. These probes do not prove actor thread progress or successful
delivery; conversation replays exercise policy/domain behavior separately.

No dependency lock, migration revision, generated schema or external wire contract
changed. No developer `.env`, operator database, external service, sibling
repository or real credential was modified. Pre-existing unrelated `LICENSE`
line-ending drift is excluded from this change.
