# Observability and operational readiness

Oria emits privacy-safe JSON metric samples to its logs and offers a private
aggregate snapshot. This demo baseline needs no metrics database, new dependency,
public endpoint or migration. See [operational telemetry v1](../contracts/operations/v1.md).

## Operator commands

Run `make metrics` using the deployment's database and Redis settings. It prints
queue status/depth/oldest age, latest consent decisions, saved onboarding/profile/cache
counts and deletion progress/retries. It does not load ciphertext, charts, identity
mappings or messages. Collect periodically if trends are needed. Database failure
produces unknown (`null`) gauges; Redis failure preserves database counts. Exit one
indicates a failed dependency/configuration check.

`make logs` follows the last 100 lines from local Compose PostgreSQL, Redis and optional
MCP containers. Host-run `make api`, `make run` and `make worker` emit to their consoles;
collect those streams with your supervisor. `make logs` does not capture host processes
or external SecondContext. Infrastructure logs do not pass through Oria's formatter;
keep them private too.

## Reading metrics

With `LOG_LEVEL=INFO`, timed attempts emit `event=metric`, a fixed name, outcome and
milliseconds. A collector can sum `value` by metric/outcome, compute error fractions,
and build latency distributions. Aggregation lives in the operator's log collector,
so it spans process restarts and worker event loops. Do not group by correlation,
update or job IDs. No external collector/dashboard is installed here.

| Signal | Meaning |
| --- | --- |
| `telegram_update` | Supported private update-handler attempt, including redelivery; permanently limited updates are handled successfully |
| `queue_admission`, `update_deduplicated`, `inbound_limited` | Admission attempt, receipt hit, locally handled limit rejection |
| `queue_publish` | Redis publication attempt, including suppressed duplicate reservations |
| `worker_dispatch` | Dispatch including duplicates, contention and not-yet-due jobs |
| `worker_process`, `worker_retry`, `worker_dead` | Claimed calculation/delivery attempt, retry scheduling, exhausted attempts |
| `database_transaction` | Commit/rollback scope including lock waits and enclosed downstream calls |
| `mcp_natal`, `mcp_transits` | Bounded calculation operation including protocol/result validation |
| `second_context_*` | Respond/remember/purge including connection-only retries and result validation |
| `telegram_send` | Outbound send; excludes polling getUpdates and callback acknowledgments |
| `consent_disclosure` | Disclosure assembled; delivery/transaction success is reported separately |
| `policy_*` | Input, output or high-stakes branch blocked; no text/draft logged |
| `deletion_process`, `deletion_retry` | Deletion attempt/retry; durable gauges confirm completion |

Nested samples cover different scopes; do not sum them as one latency total.
A handled worker error remains visible even when dispatch succeeds after scheduling
retry. Cancellation within a worker deadline may produce a cancelled inner sample;
the retry counter records subsequent handling. Final local fallback can make the
worker succeed while the downstream component reports failure.

Funnel gauges count latest decisions and retained profile rows. Accepted decisions
divided by all latest decisions, and confirmed/cache rows compared to retained users,
give a rough demo overview. Re-consent, edits, withdrawal and deletion change these
gauges; they are not cohort conversion rates. Log counters may repeat after retries
or rollback and depend on log level. PostgreSQL remains authoritative for pending work
and completion.

HTTP responses retain generated `X-Request-ID`; updates have correlation/update
context. Worker/deletion logs include durable `job_id`. Retries get distinct
correlation IDs and the same job ID. No user UUID is needed for normal logs.
Ingress `job_admitted` links normalized-update context to its worker job UUID.
HTTP request and normalized-update correlation scopes remain separate.
Startup emits environment/role and feature-presence booleans, without settings
objects, addresses or secrets.

## Diagnosing failures

| Observation | Inspect / action |
| --- | --- |
| Database check false or category `database` | PostgreSQL connectivity and `make migrate`; snapshot requires current schema |
| Redis check false or category `redis` | Redis connectivity; canonical work survives and recovery republishes it |
| Queue age/depth growing, checks healthy | Worker is running, retry/dead counters and component samples for the same job |
| `mcp_*` category `mcp` | MCP readiness/container health and supported calculation contract |
| `second_context_*` category `second_context` | Owning service availability, auth/namespace and wire contract; never query its database |
| `telegram_send` category `telegram` | Bot credentials, connectivity or API rejection; never log API exceptions |
| Deletion retries/age growing | Component errors and durable step counts; repair dependencies without skipping purge |

Unknown failures use `internal`; no traceback or exception text is included.
Telemetry identifies components, not every provider error subtype. Retry/deadline
behavior is unchanged. See [abuse controls](abuse-controls.md),
[queue recovery](worker-queue.md) and [deletion](deletion.md).

## Health and deployment

Existing Compose PostgreSQL (`pg_isready`) and Redis (`PING`) health checks gate
`make infra-up`'s wait. The MCP image's Docker health check calls calculation readiness;
`make mcp` / `make mcp-local` wait for it. Integration/container tests exercise these
checks on isolated services.

Gateway `/healthz` is liveness; `/readyz` checks PostgreSQL/Redis when webhook ingress
is enabled. They do not prove worker progress, schema compatibility, SecondContext,
bot authorization, public TLS or end-to-end delivery. Keep them private; the supplied
proxy exposes only the authenticated webhook. Combine readiness with queue snapshots
and component metrics. Gateway/worker Docker images and Compose health wiring belong
to Stage 23's application containerization.

Restart gateway/polling and workers to apply instrumentation. No migration/new secret
is required. Live HTTPS/Telegram activation and provider monitoring remain operator
checks; see [webhook setup](telegram-webhook.md).
