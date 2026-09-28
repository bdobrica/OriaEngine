# Stage 11 verification — 2026-09-28

Implemented Redis/Dramatiq UUID jobs, canonical inbound deduplication, encrypted
transient input/replies, transactional domain idempotency, bounded attempts,
per-user serialization, durable recovery and queued Telegram polling.

## Checks performed

- Generated migration `0006` using Alembic autogenerate against an isolated temporary
  PostgreSQL instance at revision `0005`; reviewed the generated table, constraints,
  indexes, identity sequence and downgrade. No developer database was migrated.
- Focused queue and Telegram tests passed, including real Dramatiq Redis delivery
  into the production job with a mocked Telegram bot.
- Final `make verify` passed: formatting/lint, strict mypy (39 source files),
  166 unit tests, 60 integration tests and 27 contract tests, including the actual
  astrology container's private and loopback MCP transport.
- The final unavailable-user ingress guard and its additional test were also checked
  with `make lint typecheck test-unit`: 167 unit tests passed. Total distinct checks
  across the final gate and unit rerun: **254 tests**.
- Two existing Starlette/AnyIO deprecation warnings remain in the unit suite.
- The earlier aggregate run exposed a test-fixture issue after Redis restart changed
  its random Docker host port. Queue fixtures now discover the current port; the
  complete integration lane passed on rerun.
- Final diff checked for unrelated changes, accidental payloads/secrets and contract
  drift. Existing `LICENSE` and `.venv` changes were excluded.

## Covered boundaries

Real PostgreSQL/Redis tests cover concurrent duplicate ingress, delayed accept replay
after decline, duplicate onboarding jobs, per-user admission/processing order,
independent users, responsive ingress during slow work, Redis flush during processing,
PostgreSQL's fallback user lock, token-safe release after lock expiry, timeout rollback,
crashed claims, crash after domain commit, send-only retries, backoff, five-attempt
exhaustion, payload expiry/erasure, consent-change suppression, pre-consent text discard,
ciphertext binding and recovery of committed-but-unpublished work. Existing integration
checks cover Redis restart without canonical database loss, migration round trips,
metadata drift, and consent/profile persistence and isolation.

Telegram replay tests verify queue dispatch, durable-ingress retry before acknowledgement,
Redis enqueue failure recovery, ignored/deleted users, privacy-safe logging, and existing
normalization/ownership controls. No actual user payloads or credentials were used.

No live Telegram send, SecondContext call, public deployment, or operator database
migration was performed. A Telegram send accepted immediately before a process crash
can still produce a duplicate reply; the domain mutation cannot repeat. Expired queue
payload cleanup requires a running worker. See [worker operation](../worker-queue.md).
