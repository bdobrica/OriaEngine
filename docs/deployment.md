# Deploy published images

Choose one complete Compose entry point:

- [compose.oria.yaml](../deploy/compose.oria.yaml): standalone OriaEngine with
  PostgreSQL, Redis, Astrology MCP, Oria migrations, gateway and worker. Configure
  an externally managed SecondContext API for conversation/deletion operations.
- [compose.full.yaml](../deploy/compose.full.yaml): OriaEngine plus SecondContext,
  its migration job and Qdrant, sharing **one PostgreSQL server**. Each component
  owns a separate database and restricted login role. No application queries the
  other component's database; Oria uses the [versioned HTTP contract](../contracts/second-context/v1.md).

`make deploy` defaults to the full file. Both entry points use published images,
production settings and the independent `oria-deploy` project. They need no build
contexts or application source mounts. The full file reuses service definitions
from the standalone file using Compose `extends`; pass only one `-f` entry point.
Keep both YAML files and the PostgreSQL bootstrap script together when copying
these deployment files. See [the shared-server decision](adr/0001-shared-deployment-postgres.md).

SecondContext follows commit `b1a58486218df138af456126fe7514a9f5b60cdd`, whose
published gateway image contains `/app/migrate` and `/app/migrations`. Select
release `0.1.1` or a compatible later version/digest.

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
- `POSTGRES_ADMIN_PASSWORD`: a separate strong bootstrap administrator password,
  required only by the full stack. It is passed only to the PostgreSQL container.
- `SECOND_CONTEXT_IMAGE`: a published `quay.io/bdobrica/secondcontext-gateway`
  version/digest containing its migration assets; publish `0.1.1` first if needed.
- `SECOND_CONTEXT_POSTGRES_PASSWORD`: a dedicated password for its own database.
  The migration/API use separate host/password fields, so URL encoding is unnecessary.
- `SECOND_CONTEXT_BEARER_TOKEN`: a long random scoped service token. The full stack
  sets `AUTH_ENABLED=true` and `AUTH_SERVICE_TOKENS=oria:=<same token>`. The subject
  namespace remains `oria`; changing it does not migrate accounts.
- `SECOND_CONTEXT_OPENAI_API_KEY`, plus optional provider base URL, chat/embedding
  models and vector size. The defaults follow the owning deployment example;
  `SECOND_CONTEXT_VECTOR_SIZE` must match the embedding model's output. Preserve
  model/vector compatibility for an existing Qdrant collection. The optional
  SecondContext knowledge service is disabled.

The full file fixes Oria's internal API URL to `http://secondcontext:8080`.
`SECOND_CONTEXT_BASE_URL` is used only in external mode. Existing env files are
never overwritten by `deploy-env`; add the new template fields privately.

OpenAI credentials belong only to SecondContext. Gateway/worker receive an explicit
application-settings allowlist; each migration receives only its owner's database
configuration, and MCP receives no application secrets. The Oria migration CLI
uses development-mode settings solely to avoid requiring unrelated HTTP/provider secrets; gateway and
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

`make deploy` pulls all images before stopping the existing gateway/worker. In
bundled mode it then stops SecondContext, after Oria callers have drained, before
starting the stack without builds. It runs `alembic upgrade head` for Oria and
`/app/migrate up` for SecondContext against their respective healthy databases.
Both applications require their migration jobs to succeed; gateway/worker also
wait for the SecondContext API health check, and the worker waits for MCP readiness.
A failed pull leaves the application running; a failed migration blocks the
affected application and its dependents. Do not run concurrent deployments.
This is a maintenance-window deployment, not a rolling or automatic rollback system.
Back up both PostgreSQL databases, the Oria encryption key and a compatible Qdrant
snapshot before upgrades; running an older image does not undo migrations.

Only the gateway is published, on `127.0.0.1:${GATEWAY_PORT}` (default 8001).
Redis and Oria database access use an internal storage network. MCP has a private
network shared only with the worker. The worker reaches SecondContext over its
private API network and does not join its storage network. The shared PostgreSQL
server joins both owners' storage networks; database authentication and privileges
preserve ownership. Qdrant joins only SecondContext's storage network. Each
application has outbound access for its provider/Telegram calls. No database,
Redis, MCP, SecondContext or Qdrant port is published.

The full stack initializes `oria` and `secondcontext` databases on a fresh
`shared_postgres_data` volume, using separate non-superuser roles, passwords and
migration jobs. Public connection access to these databases is revoked. The
administrator password never reaches either application or its migration job.
The read-only [bootstrap script](../deploy/postgres/init-app-databases.sh)
creates roles/databases only; it does not manage either component's schema.
Initialization runs once on an empty volume. Editing env passwords on an existing
volume does not rotate credentials; use an administrator-led rotation and update
all matching settings together.

Full-stack persistent volumes are `shared_postgres_data` and
`secondcontext_qdrant_data`. Standalone uses `postgres_data`. Redis is disposable
and Oria recovers canonical work from PostgreSQL. Applications and migrations run
as UID 65532 with read-only roots and dropped capabilities. The PostgreSQL server
is shared infrastructure; budget its capacity and back up both databases.

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

Keep logs private. Stopping preserves the selected storage volumes and does not
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

## Use an existing SecondContext

Select the standalone file on every deployment command and configure
`SECOND_CONTEXT_BASE_URL` to a private container-reachable external API. Retain
its matching service token and `oria` namespace:

```sh
make deploy DEPLOY_FILE=deploy/compose.oria.yaml DEPLOY_ENV=/secure/oria.env
make deploy-down DEPLOY_FILE=deploy/compose.oria.yaml DEPLOY_ENV=/secure/oria.env
```

Or select either file directly:

```sh
docker compose --env-file /secure/oria.env -p oria-deploy -f deploy/compose.oria.yaml up -d --wait
docker compose --env-file /secure/oria.env -p oria-deploy -f deploy/compose.full.yaml up -d --wait
```

Use `make deploy` for upgrades: it quiesces applications before migrations.
Standalone needs no SecondContext image, PostgreSQL administrator password,
SecondContext database password or provider key. It still needs the external API
and scoped token for the full conversation/deletion pipeline. The older Make
option `DEPLOY_SECOND_CONTEXT=false` remains a compatibility alias for standalone.
Development commands continue to use an external SecondContext.

## Existing deployment data

Changing entry points does not migrate data. The full stack deliberately uses a
new shared PostgreSQL volume: old standalone `postgres_data` and former
`secondcontext_postgres_data` volumes are not overwritten or attached. Before
switching a populated deployment, stop both applications, take owner-specific
logical backups, initialize the new shared server, and restore each database under
its matching owner role through the owning component's documented process. Keep
SecondContext's matching Qdrant data, retained deletion fences, Oria encryption
key, service namespace and session identities. Validate migrations and authenticated
purge/continuity before resuming callers. Do not attach two physical PostgreSQL
volumes to one server or assume an endpoint change moves conversation history.

Stop the old stack with its original Compose files before selecting the new one;
Compose does not automatically remove obsolete services/networks. Retain old
volumes until recovery has been validated. Keep the same project/env/file selection
for all subsequent commands. Switching between standalone and full points at
different PostgreSQL volumes, even within one project. Oria purges only the
configured SecondContext instance; backups and provider retention remain separate.

## Verification

`make test-contract` checks both Compose modes, missing required configuration,
production settings, secret isolation and private networking. It also builds local
Oria fixture images from the existing Dockerfiles and starts the standalone Compose file
in external mode with no builds or registry pulls, testing migrations, readiness,
MCP, worker UUID consumption and
restart with retained storage. These checks use generated settings and isolated
resources, without live Telegram, OpenAI or SecondContext calls. They do not
verify published registry bytes or prove a full production deployment. The normal
gate requires no sibling checkout. The gate also starts the full file's PostgreSQL
service with synthetic credentials, checks restricted roles and rejected cross-database access, and recreates the container
to verify retained storage. [Full-stack evidence](evidence/shared-postgres-deployment.md)
records owning-image migrations, authentication, purge and failure ordering.
