# Automated test harness

Run `make bootstrap`, then `make verify`. Python 3.12+, uv, Make, Docker and
Docker Compose v2 are required. No `.env`, Telegram account, OpenAI key, live
SecondContext instance or sibling checkout is required. GitHub Actions runs the
same `make verify` command.

| Command | Coverage |
| --- | --- |
| `make test-unit` | Pure and mocked domain/adapter checks |
| `make test-integration` | Real PostgreSQL/Redis, migrations, storage, ordering, retries and recovery |
| `make test-contract` | Published wire formats, golden calculations and real MCP container/transport |
| `make test-e2e` | Synthetic Telegram conversations through webhook, queue, worker and service adapters |
| `make test` | All four test lanes |
| `make verify` | Formatting, lint, strict type checking and all four test lanes |

## Isolated dependencies

[Test Compose](../deploy/compose.test.yaml) supplies PostgreSQL, Redis and an
optional astrology profile. Each integration/replay invocation creates a random
`oria-test-*` project, a fresh database password, randomly assigned loopback ports
and a project-owned volume. Fixtures remove the project and its volumes in `finally`,
including ordinary setup/test failures. Application settings are cleared from the
test environment; migrations run outside the checkout so they cannot load local
`.env`. Test fixtures never connect to the operator's application database.

`make test-integration` owns the PostgreSQL/Redis lifecycle through pytest fixtures.
Replay tests also build and start the real owned Astrology MCP image and apply all
migrations before replay. Existing contract tests separately check the deployment
image's private network, read-only filesystem and explicit loopback override.
Build/image acquisition requires network access on an uncached machine. Docker
failures fail the lane; tests do not silently skip required dependencies.

An interrupted process that cannot execute cleanup can leave a project behind.
Use `docker compose ls --all` to identify its exact `oria-test-*` project and remove
only that project's containers/volumes using the test Compose file. Keep developer
and deployment projects separate. Parallel pytest workers sharing one project are
not supported; separate command invocations have separate projects.

## Replay boundary

[Replay fixtures](../tests/e2e/fixtures) contain synthetic IDs, dates, names and
messages, never captured user traffic. Message and callback templates preserve the
Telegram wire shape. Scenario files select current buttons by label; random callback
tokens are taken from actual inline keyboards, not embedded in fixtures.

The harness invokes the real FastAPI webhook with an in-process ASGI transport,
checks its acknowledgement, consumes the real Dramatiq Redis envelope, checks that
it contains only an event UUID, and explicitly runs `EventWorker.process`. This is
a deterministic scheduler: it does not launch the four-thread worker CLI, exercise
its signal handling or prove process scheduling. Queue recovery/concurrency tests
remain in the integration lane. The replay validates encrypted storage, committed
state and erasure of transient input/reply envelopes after delivery.

The aiogram bot sends real HTTP requests to a per-test loopback Telegram fake.
The SecondContext adapter sends real HTTP requests to an authenticated, scoped
loopback fixture implementing only the [v1 consumer contract](../contracts/second-context/v1.md).
The fixture retains synthetic sessions/transcripts/memories and implements purge
tombstones. It is not upstream SecondContext or a language model. Application-level
output guarding does not erase a draft already retained remotely; deletion does.
Runtime credentials and encryption keys are generated per replay and never saved.

Replays cover consent decline, exact/unknown time, explicit ambiguous-city selection,
natal/transit fact forwarding, duplicate updates, profile editing and chart
invalidation/recalculation, local PII/high-stakes routing, unsafe generated drafts,
committed-reply delivery retries, and deletion across PostgreSQL, Redis and the
context fixture. Old accepted updates remain inert after deletion; `/start` creates
a new identity requiring fresh consent. Unknown time must expose unavailable
positions/houses/angles/aspects rather than invented values.
Confirmation sets the deletion fence immediately, so the normal conversation worker
suppresses that event's pending reply. The deletion worker sends the final notice
after cleanup. The replay preserves this existing behavior.

## Limits and optional live checks

These lanes verify deterministic contracts and application invariants. They do not
evaluate model tone or quality, Telegram account delivery, public HTTPS/proxy setup,
provider retention, backups, or upstream SecondContext/Qdrant internals. Live tone
review remains optional in [conversation worker](conversation-worker.md); live
deployment validation is described in [webhook setup](telegram-webhook.md).
