# Stage 21 verification

Scope: allowlisted JSON counter/timing samples, fixed component error categories,
request IDs and update-to-job correlation, durable worker/deletion job context, startup
feature summaries, read-only aggregate queue/funnel/deletion snapshots and local
log commands. Existing PostgreSQL, Redis and MCP health checks are reused.
No migration, dependency, generated schema or external service wire change.
See [operator guide](../operations.md) and [telemetry v1](../../contracts/operations/v1.md).

## Focused verification

- Initial unit/adapter regression: 145 passed in 30.53 seconds.
- Queue, conversation, deletion and snapshot integration: 42 passed in 228.61 seconds
  using isolated PostgreSQL/Redis and synthetic downstream/Telegram clients.
- Policy telemetry and CLI contract rerun: 23 passed in 20.15 seconds.
- Final log/correlation/adapter/contract regression: 76 passed in 25.81 seconds.
- `make format typecheck`: formatting/lint passed; strict mypy passed 59 source files.
- `make help` and dry-run `make logs metrics` expose the documented commands.

A combined test collection found a duplicate unit/contract module basename; the
contract module was renamed and the combined lane passed. Initial formatting/type
checks also caught an indentation error and decorator coroutine-signature typing;
both were corrected before focused verification completed.

## Aggregate verification

Final `make verify` passed with exit status 0:

- Ruff formatting: 158 files unchanged; lint passed.
- Strict mypy: 59 source files passed.
- Unit: 371 passed in 36.09 seconds.
- Integration: 120 passed in 625.64 seconds.
- Contract: 92 passed in 63.96 seconds, including the rebuilt real MCP container,
  generated astrology-schema checks and the operational output contract.
- Total: 583 passing tests. Two existing Starlette/AnyIO deprecation warnings remain.

Affected relative Markdown links resolve. Task whitespace checks pass. Final diff
review found no secret/runtime payload, generated-schema drift, unintended external
wire changes or unrelated source edits. The pre-existing LICENSE line-ending change
is excluded. Only documentation was finalized during/after the aggregate gate.

## Coverage

- Fixed database, Redis, MCP, SecondContext, Telegram, timeout/internal categories
  without SQL, exception, response or private message text.
- Cancellation propagation, success return preservation, real adapter validation
  failures and strict formatter rejection of arbitrary dimensions/config objects.
- Startup booleans without secrets, URLs or policy strings; typed UUID-only ingress
  job links and nested/concurrent correlation restoration.
- Real PostgreSQL aggregate queue depth/oldest age, latest consent and retained
  deletion progress/retry counts; scans do not load payload columns or mutate jobs.
- Admission deduplication without funnel inflation, claimed worker timing and the
  same durable job ID across failed and successful retry attempts.
- Independent dependency results; missing database data is null, never a healthy
  zero. CLI v1 keys, single JSON stdout, exit status and client cleanup.
- Policy/high-stakes block counters without logging input or blocked drafts.
- Existing queue ordering, encryption, consent fences, deletion and conversation
  regression tests retain their behavior.

## Limits

Metric logs are best effort and need an operator-owned collector for aggregation;
no dashboard, Prometheus server or public endpoint was deployed. Funnel gauges are
current retained state, not lifetime/cohort conversions. Docker application images
and their health wiring remain Stage 23 work. No live Telegram/paid-provider call,
public HTTPS activation, production load test or operator database mutation was
performed. Infrastructure logs and external SecondContext are outside Oria's
formatter; `make logs` covers local Compose services only.
