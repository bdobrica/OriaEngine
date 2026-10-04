# Stage 22 verification evidence

Date: 2026-10-04. Scope: isolated integration dependencies and deterministic
Telegram conversation replay. Reference: [harness guide](../testing.md).

## Implemented and inspected

- Dedicated test Compose file with ephemeral loopback ports, fresh PostgreSQL
  credentials and a randomly named project/volume; shared integration/replay lifecycle.
- Existing integration imports and migration helper remain compatible. Subprocess
  application settings are cleared; no local `.env` or operator service is used.
- Local HTTP Telegram and authenticated/scoped SecondContext fakes use the existing
  aiogram/httpx clients. The real Astrology MCP image handles natal/transit requests.
- Synthetic update templates and scenario files drive current inline keyboards,
  actual webhook acknowledgement, UUID-only Redis envelopes and `EventWorker`.
- Eleven replays cover exact/unknown time and fact forwarding, bounded place
  ambiguity, decline, duplicates, editing/recalculation, input/output/high-stakes
  policy, complete deletion, delivery retry, two-user isolation and context HTTP outage.
- Deletion seeds a fixed approved memory through the public adapter and proves
  fixture sessions/transcripts/memories are gone. Tombstoned subjects reject later
  calls; unlinked old update receipts stay inert; new `/start` requires new consent.
- `make test` and `make test-e2e` are implemented; CI keeps invoking `make verify`,
  which now includes all four required lanes.

## Verification

`make format typecheck` passed: Ruff format/lint and strict mypy (59 source files).
Focused `uv run pytest tests/e2e --tb=short --show-capture=no`: **11 passed** in
103.25 seconds, including real service startup and migrations.

Full `make verify` passed (exit 0):

| Gate | Result |
| --- | --- |
| Ruff format/lint | 166 files passed format check; lint passed |
| Strict mypy | 59 source files passed |
| Unit | 371 passed, 37.63 seconds |
| Integration | 120 passed, 548.03 seconds |
| Contract | 92 passed, 59.98 seconds |
| E2E | 11 passed, 103.46 seconds |

Total: **594 tests passed**. Two existing Starlette/AnyIO deprecation warnings
occurred in the unit lane. Mandatory lanes exercised owned disposable service
startup/cleanup; contract tests checked the real MCP deployment container as well.
Relative documentation links and final whitespace checks passed. The reviewed diff
contains only harness, workflow and related documentation changes; generated schemas
and dependency/migration files have no drift.

Early replay failures identified incorrect fixture assertions (candidate labels
versus reply text, an unambiguous bundled city, querying a profile by owner as though
it were its primary key, and the deletion fence suppressing ordinary delivery).
Those test expectations were corrected without changing production behavior.

## Limits

No live Telegram, model, upstream SecondContext/Qdrant, HTTPS/proxy, provider
retention, backup or production deployment checks were performed. The replay uses
in-process ASGI ingress and explicit Redis consumption/worker invocation; it does
not start the worker CLI or prove its thread/signal scheduling. Existing integration
coverage remains responsible for ordering, concurrency and recovery.

No runtime source, dependency lock, migration, published schema or external wire
contract changed. No developer `.env`, operator database, remote transcript or
sibling repository was modified. Unrelated pre-existing `LICENSE` drift is excluded.
