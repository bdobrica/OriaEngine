# Container publishing workflow validation

## Scope

The workflow adapts SecondContext commit
`6f4f4183cb42298ef8850b36b38801950fe4eff5` to Oria's existing application and
Astrology MCP Dockerfiles. Independently versioned images target
`quay.io/bdobrica/oria-engine` and `quay.io/bdobrica/oria-astrology-mcp`.
Both retain the repository root build context and locked runtime installation.
Version configs are excluded from the Docker context; no application, migration,
dependency lockfile or wire contract changes were made.

Publishing requires increased committed versions on a push to `main`, validates
the complete push range and pins builds to the triggering SHA. Initial `0.1.0`
configs establish a baseline without publishing. Pull requests exercise selection
without registry credentials. Registry setup and the later first version bump
remain operator actions documented in [image publishing](../image-publishing.md).
The existing application verification workflow runs independently.

## Focused checks

- `make test-releases`: 14 tests passed using real disposable Git histories.
  Cases cover either/both images, complete multi-commit push ranges, reverted bumps,
  comments/source-only edits, missing/removed configs, new-branch baselines,
  numeric ordering, malformed versions, downgrades, unavailable commits and CLI
  GitHub outputs/input validation.
- Actual `bump2version==1.0.1` commands against copies of both version configs
  selected only the intended image at `0.1.1`, without automatic commits or tags.
  The repository's version files remained at `0.1.0`.
- Executed the workflow authentication/cleanup shell blocks with synthetic
  credentials. A valid robot-style login produced the expected private Docker
  auth file (directory `0700`, file `0600`) without printing it. Missing auth,
  invalid base64, missing separator, empty username/password and invalid UTF-8
  failed without a traceback or auth file. Cleanup was idempotent.
- Actionlint 1.7.7 passed for both GitHub workflows. `make help` exposes the new
  test target; 104 local link targets in the changed documentation resolve.
- Registry inspection confirmed both pinned uv and Python base-image manifests
  include `linux/amd64` and `linux/arm64`.

## Repository gate

Created a fresh source export of the preceding commit plus the scoped changes in
a temporary directory, excluding `.env`, the previous virtual environment and
unrelated working-tree changes. `make bootstrap` installed all 104 locked packages
using available caches. `make verify` exited successfully on host Python 3.13.5:

| Check | Result |
| --- | --- |
| Ruff formatting and lint | 178 files formatted; lint passed |
| Strict mypy | 60 source files passed |
| Release selection | 14 tests passed |
| Unit | 380 passed |
| Integration | 120 passed |
| Contract | 93 passed |
| E2E replay | 11 passed |

All 618 tests passed. The contract lane built both existing Dockerfiles on amd64
and exercised real application/MCP containers, migrations, readiness, worker UUID
consumption and restart. Other lanes used isolated PostgreSQL/Redis services and
synthetic local HTTP providers. Existing Starlette/AnyIO deprecation warnings and
uv's cross-filesystem hardlink fallback did not fail verification. Final scoped
whitespace and diff review passed.

## Limits

No registry login with real credentials, GitHub workflow execution, image push,
deployment, live Telegram/model call or operator database migration was performed.
The local Docker builder has no arm64 emulator; full arm64 builds remain for the
GitHub QEMU runner. Manifest inspection is not evidence of successful arm64 builds.
Quay repository permissions and the GitHub `QUAY_AUTH` secret remain unverified.

Operator `.env`, services and data were not used or changed. Pre-existing unrelated
`LICENSE` line-ending changes were excluded from this change. Image publication
does not complete the Stage 25 MVP release gate.
