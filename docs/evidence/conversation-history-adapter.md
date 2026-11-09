# OCH2 capability-gated adapter — 2026-11-09

Scope: Oria's typed managed Responses boundary, capability cache, preparation,
draft/header validation and generated/local/abandon finalization. The worker still
uses legacy Responses. No new consent copy, configuration switch, database schema,
dependency, deployment or live capture is introduced. OCH3 remains next.

The public schema and fixtures remain byte-identical to SecondContext CH3
(`f0dd268`); no cross-repository implementation types or database access are used.
See the [adapter reference](../conversation-history-adapter.md).

## Focused validation

- `.venv/bin/python -m pytest tests/contract/test_history_adapter.py tests/contract/test_history_schema.py tests/contract/test_second_context.py -q`:
  **246 passed**. Synthetic HTTP validates public fixture conformance, exact
  owner/session/turn/response binding, closed receipts, frozen request round trips,
  recent/explicit headers and current source references, draft versus acceptance,
  all finalize variants, service and subject-bound auth, cache scope/expiry/refresh,
  unsupported capability/configuration and unchanged legacy requests.
- Adversarial cases include wrong/duplicate/missing headers, unsafe numeric values,
  invalid Unicode and duplicate JSON keys, blank text, mismatched receipts, bounded
  decoded streams, known versus unknown error codes, no ambiguous-write retries,
  exact connection-establishment retries, total deadlines and cancellation.
- `python3 scripts/sync_history_contract.py --source /mnt/www/github/SecondContext --check`:
  passed. The checked-in public schema/fixtures are unchanged.

## Repository gate

`make verify UV='python3 /tmp/oria-och2-uv.py'` passed:

- Formatting/lint: 249 Python files checked; lint clean.
- Strict mypy: 78 source files passed.
- Release-selection tests: 14 passed.
- Unit: 592 passed; two existing Starlette/httpx/AnyIO deprecation warnings.
- Integration: 176 passed against isolated PostgreSQL/Redis services.
- Contract: 379 passed, including the real astrology container and isolated
  development/deployment stack smoke tests, plus the unchanged legacy adapter.
- End-to-end: 13 replay cases passed with isolated services/local HTTP fakes.

Total pytest cases: **1,160 passed**, no skips. Because `uv` is unavailable on the
host PATH, the temporary `UV` runner mapped `uv run <command>` to the corresponding
existing `.venv/bin/<command>`; it did not change the Make targets or dependencies.
The initial sandbox run stalled in the existing async abuse-control unit test and
was interrupted. The full gate then passed outside the sandbox with local sockets
and Docker available. Test fixtures tore down their uniquely named Oria Compose
projects/volumes; the live project was not changed.

Final diff whitespace, documentation links and public snapshot comparison passed.
No generated artifacts, accepted ADR meanings or unrelated source files changed.

## Limits

These HTTP mocks verify the consumer boundary, not provider history storage or
model-input selection. No real SecondContext provider, paid model/Decisions, private
Telegram, release/image publication or live deployment check was run for this slice. OCH3/OCH4
must test durable worker recovery, consent/withdrawal, source invalidation and
cross-service dialogue replay before OCH5 rollout.
