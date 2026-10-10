# Deploy published images

[deploy/compose.images.yaml](../deploy/compose.images.yaml) starts all Oria-owned
services from images: PostgreSQL, Redis, Astrology MCP, an explicit migration job,
the webhook gateway and worker. There are no build contexts or source mounts.
It uses production application settings and a separate `oria-deploy` Compose
project/volume from the `oria-local` development stack.

SecondContext remains a separately managed service, accessed through the
[versioned HTTP contract](../contracts/second-context/v1.md). Its currently inspected
gateway Dockerfile packages only the API, without its migration command or SQL
files; that image alone cannot initialize fresh SecondContext storage. Provision
its own PostgreSQL/Qdrant and migrations using the owning repository before using
this deployment. Oria does not connect to that database or copy its schema.

## Configure

Install Docker with Compose v2 supporting `--wait`, GNU Make and this checkout's
deployment files. No host Python, uv or sibling checkout is needed to operate the
Oria stack. First [publish the images](image-publishing.md); initial `0.1.0` version
configs are a baseline, not published releases. For private Quay repositories,
authenticate the deployment host separately with `docker login quay.io`, using
read-only pull credentials. Registry credentials stay in Docker's credential
store, outside the deployment environment file and application containers.

```sh
make deploy-env
```

This creates ignored `deploy/.env` from [the template](../deploy/.env.example),
requests mode `0600` for a new file, and never replaces an existing file.
The storage filesystem must honor those permissions. For a Windows/OneDrive checkout,
keep real deployment secrets on a private Linux filesystem instead, using
`DEPLOY_ENV=/secure/oria.env` consistently.
Git ignore rules do not prevent cloud synchronization. The file's parent directory
must already exist and be protected; secure existing files separately.
Edit it privately and fill in:

- `ORIA_APP_IMAGE` and `ORIA_ASTROLOGY_IMAGE`: complete published version tags or
  immutable digest references. For example, `quay.io/bdobrica/oria-engine:0.1.1`
  only after that release succeeds. Prefer digests; avoid `latest` for upgrades.
- `POSTGRES_PASSWORD`: a strong password, preferably hexadecimal. If it contains
  URL delimiters, also set its percent-encoded form in `POSTGRES_PASSWORD_URLENCODED`.
  Changing this file does not change credentials in an existing database volume.
- A bot token, public HTTPS webhook base URL and random webhook secret. The base
  URL excludes `/telegram/webhook`; an optional URL prefix needs proxy rewriting.
- A stable, securely backed-up [profile encryption key](birth-profiles.md#encryption-and-keys).
  Retain the same key, key version and policy across restarts/upgrades.
- `SECOND_CONTEXT_BASE_URL`: a private API URL reachable from containers;
  `localhost` refers to each Oria container, not the host. Set
  `SECOND_CONTEXT_BEARER_TOKEN` to its scoped service token. SecondContext uses
  `AUTH_ENABLED=true` and `AUTH_SERVICE_TOKENS=oria:=<same token>`. This stack fixes
  the subject namespace to `oria`; do not switch an existing account deployment's
  namespace without a reviewed migration.

OpenAI credentials belong only to SecondContext. Gateway/worker receive an explicit
application-settings allowlist; migration receives only its database configuration,
and MCP receives no application secrets. The migration CLI uses development-mode
settings solely to avoid requiring unrelated HTTP/provider secrets; gateway and
worker run in production mode. No development `.env` is mounted or consumed.

Shell variables override Compose env-file values. Use a clean deployment shell;
do not print interpolated `docker compose config` output because it contains secrets.
`make deploy-check` checks Compose configuration quietly; application startup also
validates setting formats. Neither verifies registry permissions or live credentials.

## Start and register ingress

```sh
make deploy-check
make deploy
```

`make deploy` pulls all images before stopping the existing gateway/worker, then
starts the stack without builds. It waits for PostgreSQL/Redis, runs
`alembic upgrade head`, requires successful migration completion and MCP readiness,
and waits for gateway/worker health. A failed pull leaves the application running;
a failed migration leaves gateway/worker stopped. Do not run concurrent deployments.
This is a maintenance-window deployment, not a rolling or automatic rollback system.
Back up PostgreSQL and its encryption key before upgrades; running an older image
does not undo migrations.

Only the gateway is published, on `127.0.0.1:${GATEWAY_PORT}` (default 8001).
PostgreSQL/Redis use a private internal storage network. MCP uses a separate private
internal network shared only with the worker. Gateway/worker have outbound network
access for Telegram and the configured SecondContext endpoint. Only PostgreSQL has
a persistent named volume; Redis is disposable and canonical work is recovered
from PostgreSQL. Application/MCP roots are read-only with dropped capabilities.

Provide HTTPS with your existing host reverse proxy/tunnel, forwarding only
`/telegram/webhook` to the loopback gateway and preserving the received secret
header. See the [proxy example](../deploy/nginx.webhook.conf.example) and
[webhook requirements](telegram-webhook.md#proxy-and-tls). A proxy in another
container cannot reach the host's loopback mapping without additional operator
network configuration. This Compose file does not obtain certificates or expose
health, debug, database, Redis or MCP endpoints publicly.

Stop any polling process for this bot, then explicitly register:

```sh
make deploy-webhook-set
```

This runs the existing bounded management command inside the gateway with the same
deployment settings, preserving pending updates. `make deploy-webhook-delete`
explicitly removes registration and preserves pending updates. Starting/stopping
the stack never changes Telegram registration. Health checks do not prove public
TLS, Telegram delivery or SecondContext continuity/purge; exercise those with
synthetic users before public use.

## Inspect and stop

```sh
make deploy-logs
make deploy-down
```

Keep logs private. Stopping preserves the named PostgreSQL volume and does not
remove webhook registration; Telegram can retry while the gateway is unavailable.
There is deliberately no deployment volume-reset command. Runtime configuration,
backups, provider retention and the encryption key need their own protected storage.

To use a different private env file or independent project, pass the same overrides
to every command, including webhook and stop commands:

```sh
make deploy DEPLOY_ENV=/secure/oria.env DEPLOY_PROJECT=oria-personal
```

The env file's parent directory must already exist; `deploy-env` also supports
these overrides. One bot belongs to one database deployment. Do not reuse a live
bot in the development stack or change the project name expecting its old volume
to follow. The [Stage 25 release gate](../TODO.md#stage-25--mvp-release-gate) and
[known limitations](limitations.md) remain separate from Compose startup.

## Verification

`make test-contract` checks missing required configuration, production settings,
secret isolation and private networking. It also builds local fixture images from
the existing Dockerfiles and starts this exact Compose file with no builds or
registry pulls, testing migrations, readiness, MCP, worker UUID consumption and
restart with retained storage. These checks use generated settings and isolated
resources, without live Telegram, OpenAI or SecondContext calls. They do not
verify published registry bytes or prove a full production deployment.
