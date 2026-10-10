# Published-image Compose deployment validation

## Scope

[The deployment stack](../deployment.md) uses the application and Astrology MCP
image references supplied by an operator. It contains no build contexts, source
mounts or env-file mounts. PostgreSQL, Redis, migration, gateway, worker and MCP
use a separate Compose project from development. Only the loopback gateway port
is published; storage and MCP remain on distinct private internal networks.

Gateway/worker use production settings and explicit integration settings.
Migrations receive only database configuration; MCP receives no application
secrets. SecondContext remains separately managed through its versioned HTTP
contract. Its inspected gateway image packages neither the migration command nor
SQL files, so this change does not claim to provision its fresh storage. No sibling
files, wire contracts, migrations, dependency definitions or lockfiles were changed.

The Make commands validate configuration, pull images before stopping the current
application, and require successful migrations/readiness before application
startup. Webhook registration/removal remains explicitly invoked and preserves
pending updates. Deployment teardown preserves PostgreSQL data.

## Focused checks

- Eleven configuration checks passed, rendering Compose with generated settings
  and no operator `.env`: production validation, private networks, no builds,
  secret allowlists, template coverage, tags/digests and each missing required value.
- The image-deployment lifecycle test passed against locally built fixture images
  and the exact deployment Compose file with `up --no-build`. It verified schema
  revision `0008`, gateway/worker/MCP health, non-root/read-only application images,
  disabled production OpenAPI, unauthorized webhook rejection, failed readiness
  probes, UUID consumption by the real worker, private MCP calculation and restart
  with retained database storage. Its own resources were removed afterward.
- Exercised the Make orchestration with a disposable Docker command stub: custom
  env/project overrides were preserved, quiet validation preceded pulling, and a
  failed pull prevented both stopping and starting the application.
- `make deploy-env` produced mode `0600` on a temporary Linux filesystem and did
  not replace an existing file. A synthetic file in this Windows-mounted checkout
  still reported `0777` after `chmod 600`; the guide directs WSL/OneDrive users to
  a protected Linux filesystem through `DEPLOY_ENV`. No real credential file was
  created. Git ignores `deploy/.env` and tracks the blank template.
- `make help` exposes all deployment commands. Local documentation links and
  scoped whitespace checks passed.

## Repository gate

Exported the preceding commit plus scoped changes into a fresh temporary source
tree without the operator `.env`, prior virtual environment or unrelated `LICENSE`
line-ending drift. `make bootstrap` installed the 104 locked packages using
available caches. `make verify` exited successfully on Python 3.13.5:

| Check | Result |
| --- | --- |
| Ruff formatting / lint | 181 files formatted; lint passed |
| Strict mypy | 60 source files passed |
| Release selection | 14 passed |
| Unit | 380 passed |
| Integration | 120 passed |
| Contract | 105 passed |
| E2E replay | 11 passed |

All 630 tests passed. The contract lane exercised both development and image-based
deployment lifecycles with locally built amd64 fixtures. Provider interactions
used synthetic local services; existing Starlette/AnyIO deprecation warnings and
uv's hardlink-to-copy fallback did not fail verification.

## Limits

No published image was pulled, no registry credentials or actual runtime secrets
were used, and no live Telegram/model/SecondContext calls, public TLS checks,
webhook registration, operator migrations or deployment occurred. Registry bytes,
arm64 deployment, backup/restore and deployed SecondContext continuity/purge remain
unverified. Operator configuration, services, volumes and sibling working-tree
changes were left untouched. The Stage 25 release gate remains pending.
