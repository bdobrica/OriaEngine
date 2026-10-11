# Bundled SecondContext deployment validation

## Scope

[The deployment overlay](https://github.com/bdobrica/OriaEngine/blob/c9093bb/deploy/compose.secondcontext.yaml) follows
SecondContext commit `b1a58486218df138af456126fe7514a9f5b60cdd`. `make deploy`
includes it by default; `DEPLOY_SECOND_CONTEXT=false` preserves the external mode
for every deployment Make command. Development remains unchanged.

SecondContext's gateway image runs its own `/app/migrate up` against its dedicated
PostgreSQL before API startup. Oria callers wait for API health. Dedicated Qdrant
storage, volumes and internal backend networking preserve ownership: no Oria
process joins SecondContext's storage network or uses its database credentials.
The worker uses the private HTTP API network and the existing scoped v1 contract.
The same Oria bearer token configures the owning `oria:` service credential;
provider credentials are supplied only to the SecondContext API. Its API/migration
containers are non-root, read-only and have dropped capabilities. Knowledge stays
disabled. No wire contract, schema, application source or dependency changed.

## Focused validation

All 15 deployment configuration tests passed against the repository files,
covering external and bundled modes, private networking, separate credentials,
migration ordering, secret allowlists, template coverage and missing required
configuration. External mode requires no bundled image, database password or
provider key.

Exercised both Make modes with a disposable Docker command stub. Every deploy operation
honored custom env/project settings; pulling preceded stopping, Oria callers
stopped before SecondContext, and failed pulls caused no stop/start operation.

Built a temporary amd64 SecondContext image from a clean Git archive of the exact
owning commit. Combined it with existing local Oria fixture images and both
repository Compose files, using generated credentials, empty canonical storage,
random project/loopback gateway port and no operator env file. Verified:

- The full stack started and the owning migration tool reported
  `version=3 dirty=false`.
- SecondContext, gateway, worker and MCP became healthy, with read-only roots and
  UID/GID 65532.
- The real Oria adapter in the worker performed authenticated subject purge twice
  through the private HTTP boundary. A later scoped response request received 410
  before model execution, confirming the deletion fence.
- After stopping callers and then the owning API, repeated migrations and restart
  preserved that fence and idempotent purge.
- An intentionally failing owning migration command blocked SecondContext API,
  Oria gateway and worker startup.
- Cleanup removed only this test project's containers/networks/storage and its
  temporary SecondContext image. No owning SQL files or runtime types were copied
  into Oria, and no sibling files were modified.

## Repository verification

Created a clean temporary source export of the preceding commit plus scoped
changes, excluding operator `.env`, the prior virtual environment and unrelated
`LICENSE` drift. To accommodate the exhausted host address pools, only the export's
Compose files received unused explicit IPAM subnets; service configuration and
application/test source remained unchanged. `make bootstrap` installed all 104
locked packages from available caches. `make verify` passed on Python 3.13.5:

| Check | Result |
| --- | --- |
| Ruff formatting / lint | 182 files formatted; lint passed |
| Strict mypy | 60 source files passed |
| Release selection | 14 passed |
| Unit | 380 passed |
| Integration | 120 passed |
| Contract | 109 passed |
| E2E replay | 11 passed |

All 634 tests passed, with no test excluded. The normal gate built Oria application
and MCP images and exercised isolated dependency/container lifecycles and synthetic
conversation replays. It does not build or depend on a sibling checkout;
the owning SecondContext image test above is separate. Existing Starlette/AnyIO
deprecation warnings and uv's hardlink fallback did not fail validation. Local
documentation links and final scoped whitespace/diff checks passed.

## Host networking and limits

Initial startup attempts failed because this Docker daemon's default address
pools were exhausted. Validation used temporary IPAM overrides with unused subnets,
checked against existing Docker subnets and host routes. No existing network was
removed and no daemon/network settings were changed. Repository network defaults
remain normal Compose allocation; deploying on this host requires sufficient pool
capacity or an operator-selected IPAM override.

No published image was pulled or pushed, no real provider/Telegram credentials were
used, and no operator storage, webhook, public TLS or live model was exercised.
The local owning service test used synthetic credentials and purge of an absent
subject; it does not establish deployed conversation continuity or vector erasure
for a populated production index. Arm64 runtime, registry bytes, backup/restore,
provider behavior and live release checks remain separate. The Stage 25 gate
remains pending. Pre-existing unrelated `LICENSE` and sibling working-tree changes
were left untouched.
