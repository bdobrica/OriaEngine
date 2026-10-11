# Deploy published images

[deploy/compose.images.yaml](../deploy/compose.images.yaml) starts all Oria-owned
services from images: PostgreSQL, Redis, Astrology MCP, an explicit migration job,
the webhook gateway and worker. By default, `make deploy` also includes
[the SecondContext overlay](../deploy/compose.secondcontext.yaml): its API,
own migration job, PostgreSQL and Qdrant. There are no build contexts or source mounts.
It uses production application settings and a separate `oria-deploy` Compose
project/volume from the `oria-local` development stack.

SecondContext remains the owner of its storage, accessed by Oria only through the
[versioned HTTP contract](../contracts/second-context/v1.md). The overlay follows
SecondContext commit `b1a58486218df138af456126fe7514a9f5b60cdd`, whose gateway image
includes `/app/migrate` and `/app/migrations`. Use its published `0.1.1` release
or a compatible later version/digest. Oria does not connect to that database or
copy its schema. [External mode](#use-an-existing-secondcontext) remains available.

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
- `SECOND_CONTEXT_IMAGE`: a published `quay.io/bdobrica/secondcontext-gateway`
  version/digest containing its migration assets; publish `0.1.1` first if needed.
- `SECOND_CONTEXT_POSTGRES_PASSWORD`: a dedicated password for its own database.
  The migration/API use separate host/password fields, so URL encoding is unnecessary.
- `SECOND_CONTEXT_BEARER_TOKEN`: a long random scoped service token. The overlay
  sets `AUTH_ENABLED=true` and `AUTH_SERVICE_TOKENS=oria:=<same token>`. The subject
  namespace remains `oria`; changing it does not migrate accounts.
- `SECOND_CONTEXT_OPENAI_API_KEY`, plus optional provider base URL, chat/embedding
  models and vector size. The defaults follow the owning deployment example;
  `SECOND_CONTEXT_VECTOR_SIZE` must match the embedding model's output. Preserve
  model/vector compatibility for an existing Qdrant collection. The optional
  SecondContext knowledge service is disabled.

The overlay fixes Oria's internal API URL to `http://secondcontext:8080`.
`SECOND_CONTEXT_BASE_URL` is used only in external mode. Existing env files are
never overwritten by `deploy-env`; add the new template fields privately.

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
PostgreSQL/Redis use a private internal storage network. MCP uses a separate private
internal network shared only with the worker. The worker reaches SecondContext on
a separate private API network; it cannot join SecondContext's storage network.
SecondContext alone joins its own storage network and provider egress network.
Gateway/worker retain outbound access for Telegram. Neither SecondContext's API,
PostgreSQL nor Qdrant publishes host ports. Persistent volumes are `postgres_data`,
`secondcontext_postgres_data` and `secondcontext_qdrant_data`; Redis is disposable
and canonical Oria work is recovered from its PostgreSQL. Application/MCP and
SecondContext API/migration roots are read-only and run as UID 65532 with dropped
capabilities.

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

Keep logs private. Stopping preserves all three storage volumes and does not
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

Set `DEPLOY_SECOND_CONTEXT=false` on every Make deployment command to use only
the Oria Compose file. Configure `SECOND_CONTEXT_BASE_URL` to the private,
container-reachable external API and retain its matching service token/namespace:

```sh
make deploy DEPLOY_SECOND_CONTEXT=false DEPLOY_ENV=/secure/oria.env
make deploy-down DEPLOY_SECOND_CONTEXT=false DEPLOY_ENV=/secure/oria.env
```

This mode needs no SecondContext image, database password or provider key and
preserves the previous external integration. Host `localhost` is not reachable
through a container's `localhost`. Development commands still use an external
SecondContext and are unchanged.

An endpoint change does not migrate conversation data or deletion markers. Before
moving an existing external instance into the bundle, migrate/restore its owned
PostgreSQL and matching Qdrant data through the owning service's deployment process,
or continue using external mode. Oria's purge reaches only the configured instance.
Keep namespace/session identities stable. Stop with the same mode/project settings
used to start the stack; changing the selected Compose files does not clean up an
old service deployment automatically.

## Verification

`make test-contract` checks both Compose modes, missing required configuration,
production settings, secret isolation and private networking. It also builds local
Oria fixture images from the existing Dockerfiles and starts the base Compose file
in external mode with no builds or registry pulls, testing migrations, readiness,
MCP, worker UUID consumption and
restart with retained storage. These checks use generated settings and isolated
resources, without live Telegram, OpenAI or SecondContext calls. They do not
verify published registry bytes or prove a full production deployment. The normal
gate requires no sibling checkout. A separate [bundled-stack validation](evidence/bundled-secondcontext.md)
uses the owning SecondContext image and verifies migrations, service authentication,
idempotent purge, retained fences and startup refusal after failed migrations.
