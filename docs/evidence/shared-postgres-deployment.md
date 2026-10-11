# Shared PostgreSQL deployment verification

Date: 2026-10-11. See [the deployment guide](../deployment.md) and
[ADR 0001](../adr/0001-shared-deployment-postgres.md).

## Scope

Two single-file Compose entry points replace the base/SecondContext overlay:
standalone OriaEngine and combined OriaEngine/SecondContext. The combined entry
point extends Oria service definitions and uses one PostgreSQL server, separate
database owners, owner-specific migrations and private SecondContext Qdrant storage.
The full stack initializes a new shared PostgreSQL volume; existing data is not
copied or overwritten. No versioned HTTP or astrology contract changed.

## Focused checks

`uv run pytest tests/contract/test_image_deployment.py -q` passed all 17 tests.
Configuration checks cover both entry points, missing settings, production
validation, image-only operation, private networks, scoped service authentication,
provider-key isolation and exclusion of the administrator credential from callers
and migration jobs.

The real PostgreSQL test starts only the full file's database service in a random
project. Fresh initialization creates both databases with restricted owner roles.
Passwords containing quotes, backslashes and dollar signs authenticate over the
container network; a wrong password fails. Each owner can create/use its own table,
while cross-database connections and assuming the other role fail. Both tables
survive container removal/recreation with retained storage. The fixture removes
only its own project and volumes afterward. Shell syntax checking also passed.

A temporary Docker command recorder checked eight Make invocation cases: default
full stack, explicit standalone, the legacy external-mode alias and an explicit
absolute full-file path overriding that alias, each with successful or failed pulls.
A private env path containing spaces and the selected project/file propagated to
every command. Pull failure occurred before any stop; successful full deployment
stopped Oria callers before SecondContext and then started without builds.

## Full-stack runtime check

A temporary image was built from SecondContext commit
`b1a58486218df138af456126fe7514a9f5b60cdd`. Local Oria fixture images supplied the
application and MCP. The actual combined entry point started with random synthetic
credentials, an isolated project, fresh storage and default Docker networking.
No operator env file or provider/Telegram account was used.

Both owners' migration jobs completed. SecondContext reported `version=3 dirty=false`.
SecondContext, gateway, worker and MCP reached healthy status with read-only roots
and UID 65532. The real Oria HTTP adapter purged a synthetic subject twice; a later
response request received 410 before reaching a model. Repeating migrations and
restarting preserved the deletion fence. Deliberately failing the SecondContext
migration prevented its API, Oria gateway and worker from starting. The runtime
check removed its own containers, networks, volumes and temporary image.

## Repository gate

`make bootstrap verify UV=/home/bogdan/.local/bin/uv` passed from a fresh temporary
source export containing the scoped change, without operator configuration,
existing virtualenvs or changes to Compose networking. Host Python was 3.13.5;
Compose was v2.40.3. Bootstrap used the locked dependency cache. Formatting, lint,
strict type checking and all 636 tests passed:

| Lane | Passed |
| --- | ---: |
| Release checks | 14 |
| Unit | 380 |
| Integration | 120 |
| Contract | 111 |
| E2E | 11 |

The contract lane built local application/MCP fixtures and exercised both
development and standalone image deployment, including migrations, readiness,
worker consumption, private MCP and retained schema. The shared-server test also
passed with the bootstrap script at its committed non-executable file mode.
The two existing Starlette/AnyIO deprecation warnings and uv hardlink fallback
were non-fatal. All 307 relative documentation link targets existed; anchors
were not checked. Scoped staged whitespace checks passed.

## Operator cleanup and limits

With explicit operator authorization, 13 existing Oria test/SecondContext
containers and their 10 networks were removed. Existing data volumes and images
were retained; unrelated project networks were left alone. This restored capacity
in Docker's default address pools; no temporary IPAM overrides were needed here.
The existing test harness left one additional MCP container/network after the
aggregate gate; these were removed manually. That unrelated cleanup limitation
was not changed by this deployment task.

No published registry bytes, live Telegram/OpenAI calls, public HTTPS, operator
storage restore or actual production deployment were verified. Existing volumes
remain available for an explicit owner-led backup/restore transition. The Stage 25
release gate remains open.
