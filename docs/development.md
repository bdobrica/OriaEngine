# Docker development stack

After `make env` and private configuration, `make dev` builds and starts all
OriaEngine-owned services: PostgreSQL, Redis, a migration job, the HTTP gateway,
the conversation worker and Astrology MCP. Docker Compose v2 with `--wait` and
GNU Make are required; host Python/uv are needed only for host commands and tests.
The first image build may take several minutes.

## Configuration

Keep `.env` uncommitted. Set `TELEGRAM_BOT_TOKEN` and a stable
`PROFILE_ENCRYPTION_KEY` as described in [key management](birth-profiles.md).
For enabled webhook ingress, also set a random `TELEGRAM_WEBHOOK_SECRET`.
Empty webhook secret keeps the HTTP skeleton available for a polling demo;
the worker still requires the bot token and encryption key. Gateway and worker
receive the same key, policy version, limits and SecondContext configuration.

Replace the local `POSTGRES_PASSWORD` placeholder. Compose constructs the
container database URL using that password and `postgres:5432`. For passwords
containing URL delimiters, also set `POSTGRES_PASSWORD_URLENCODED` to their
percent-encoded form. Keep host `DATABASE_URL` consistent for `make run`,
`make migrate` and `make metrics`. Changing a password in configuration does
not change an existing PostgreSQL volume's credentials.

Container Redis and MCP URLs are fixed to `redis:6379` and
`http://astrology-mcp:8000/mcp`; host URL settings remain available for the
existing host workflow. `GATEWAY_PORT`, `POSTGRES_PORT` and `REDIS_PORT` control
loopback host ports (defaults 8001, 5432 and 6379).

Set `SECOND_CONTEXT_DOCKER_URL` to the API address reachable from a container.
It overrides `SECOND_CONTEXT_BASE_URL` inside the stack; when absent, the base
URL is used. With neither set, it defaults to `http://host.docker.internal:8080`.
The example env file sets the Docker URL explicitly. `localhost` inside the
worker refers to that worker, not the host or another container.

On Linux, Compose maps `host.docker.internal` to the host bridge address. A
host SecondContext listener must accept traffic on that address; a listener
bound only to `127.0.0.1` is insufficient. A separately managed container can
publish its API on a host interface reachable from the bridge, or use another
reachable private URL. Restrict exposure with the owning deployment's network
controls. Oria does not start SecondContext, join its database or read its secrets.
Use its [service authentication and subject purge contract](second-context.md)
for conversation and complete deletion. OpenAI credentials belong to SecondContext.

## Start, inspect and stop

```sh
make dev
make logs
make down
```

`make dev` waits for PostgreSQL/Redis health, runs `alembic upgrade head` in the
application image and requires migration success before gateway/worker startup.
The worker also waits for real MCP readiness. Failed migrations prevent application
startup. Run only one `make dev`/migration operation at a time. Migrations remain
an explicit development orchestration step, not an HTTP startup side effect.

The gateway listens on `0.0.0.0:8001` inside its container, with host access only
at `http://127.0.0.1:<GATEWAY_PORT>`. The host launcher still binds loopback by
default; its optional `--host 0.0.0.0` is intended for a private container listener.
Uvicorn access logs remain disabled in both modes. Health probes emit no diagnostics.

`make down` removes this local project's containers/networks while preserving
PostgreSQL's named volume. `make dev` reapplies migrations on the next start.
These commands share the existing `oria-local` infrastructure project/volume.
Stop host workers/gateways before switching modes; use one bot per database.
`make infra-reset` remains the explicit guarded, destructive volume reset.
Keep the local env file available for Compose commands, even when stopping.

Code is installed from the locked build, with no source or env bind mount.
Rerun `make dev` after edits/settings changes to rebuild/recreate services.
Gateway, worker and migration job share one image; the build allowlist excludes
`.env`, tests and operator files. Application/MCP containers run as UID 65532,
with read-only roots, dropped capabilities and no privilege escalation. Only
application containers get their necessary configured integration secrets;
migrations get the database URL, and MCP receives no application secrets.
The worker has a bounded writable `/tmp` for its payload-free heartbeat.

## Telegram demo and webhook

For the quickest demo, use a development bot with no active webhook:

```sh
make dev
make run
```

Host polling uses the existing loopback DB/Redis URLs and queues work for the
container worker. Do not start another `make worker`; MCP is reached by the worker
on its private internal network and needs no host port. Stop polling with Ctrl-C,
then `make down`. Polling refuses an active webhook and never removes one.

For webhook testing, enable the secret, configure a public HTTPS proxy/tunnel
forwarding only `/telegram/webhook` to the loopback gateway, stop polling and
explicitly run `make webhook-set`. See [webhook setup](telegram-webhook.md).
Starting the stack never registers a webhook, contacts Telegram for setup or
creates a public TLS endpoint. This development Compose stack is not a production
deployment definition.

## Health and verification

Gateway Docker health calls `/readyz`, including DB/Redis when webhook ingress is
enabled. Worker health requires a recovery-loop heartbeat no older than 90 seconds,
then bounded PostgreSQL `SELECT 1` and Redis `PING`. The marker is removed before
startup and on graceful shutdown; it contains no IDs or data. The worker has a
150-second stop grace period to allow an in-flight bounded recovery attempt and
its existing 70-second Dramatiq drain.
MCP retains its synthetic-calculation readiness probe. These checks do not prove
SecondContext capabilities, Telegram credentials, actor thread progress, public
TLS or successful delivery. Unhealthy containers are reported by Docker; health
failure alone does not trigger Docker's restart policy.

`make logs` includes application, migration and infrastructure container logs;
host processes and external SecondContext still have separate logs. Keep logs
private. `make metrics` uses the host DB/Redis settings for canonical queue and
deletion status; see [operations](operations.md).

`make test-contract` includes an isolated build/start/health/migration/container
test of these deployment files, actual worker UUID consumption, private MCP
calculation and restart with retained schema. It uses random ports/project,
generated credentials and an unavailable synthetic context endpoint, then removes
only its own resources. No live Telegram/LLM is called. `make verify` also runs
the [conversation replays](testing.md) and all other mandatory lanes.
