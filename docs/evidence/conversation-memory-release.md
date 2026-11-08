# Conversation-memory release evidence

Date: 2026-11-08. Published and deployed to `oria-live-test`.

The release uses Oria application/MCP image version `0.2.0`, SecondContext gateway
`0.2.1` and disclosure `2026-11-08.5`. Versioned consent covers the expanded
learning/retention lifecycle, birthday samples, house themes and symbolic ratings.
No ordinary reading gains a recurring general disclaimer.

## Source verification

- Focused consent/startup checks: 106 passed. After the final policy-version guard
  and disclosure checks, the full unit suite passed 592 tests with two existing
  upstream TestClient deprecation warnings.
- Synthetic Telegram/SecondContext HTTP replays passed 13 tests against real
  isolated PostgreSQL/Redis and MCP. New fixtures cover partner birth, wedding,
  house/phone purchase, pet adoption, job change, business/non-profit foundation
  and parents' divorce, CRUD, opt-out, withdrawal and versioned re-consent.
- SecondContext's root `make verify` passed using the installed Go toolchain,
  including mandatory dependency-backed tests without skipped cases. Its packaging
  check passed against fresh isolated storage, checking migration `000004`, new
  projection tables, scoped purge, repeat migration and startup blocked by dirty schema.
  Release fixes invoke its integration script through Bash and update the old
  packaging assertion from schema 3 to 4. No service authority or storage boundary changes.
- Oria's final `make verify` passed: formatting/lint, strict mypy over 77 source
  files, 14 release-selection checks, 592 unit, 176 integration, 193 contract and
  13 E2E tests. No lane was skipped. Both contract generators passed `--check`;
  existing natal/transit schemas and other published wire shapes are unchanged.
  The release-check script also passed explicit strict mypy with source imports.
- SecondContext `0.2.1` source `683fa7e83512afa0172e79f14f38c31a2c61d47a`
  passed both [CI jobs](https://github.com/bdobrica/SecondContext/actions/runs/42515453500)
  and [publication](https://github.com/bdobrica/SecondContext/actions/runs/42515453537).
- Application/MCP `0.2.0` source `c4e142953ade5fcdc40d08af09babefa1dc66ca6`
  passed [CI](https://github.com/bdobrica/OriaEngine/actions/runs/42516316507) and
  [publication](https://github.com/bdobrica/OriaEngine/actions/runs/42516316551).
  Both release manifests include linux/amd64 and linux/arm64; pulled source/version
  labels match the expected commits.

## Deployment and live checks

- Only the existing `oria-live-test` project was deployed. Published digests below
  match the running application, worker, MCP and SecondContext images. Seven services
  are healthy; both migration jobs exited zero. Oria reports schema `0012`;
  SecondContext's own migration tool reports version 4, not dirty.
- Callers were drained before owner-specific database backups and a cold Qdrant
  storage archive. Archive structure was checked; a backup restore was not exercised.
  Private configuration/key backups remain outside the repository. Existing private
  settings, encryption key, namespace and webhook were preserved; `deploy/.env`
  remains mode `0600`. No unrelated host containers were maintained or pruned.
- Before enabling ingestion, the published worker image ran
  `scripts/check_linked_release.py --generate` against the new private services.
  The configured real AI provider generated linked readings; the first passed the
  application response guard unchanged. Real MCP calls supplied sampled event
  charts, static synastry and supported overlays. No synthetic model replies were
  used in this live check.
- The same check passed authenticated capabilities, duplicate upserts, typed
  retrieval, independent subject isolation, correction/stale-reference rejection,
  selective erasure, duplicate delete, denied resurrection, full purge and delayed
  write fencing. Fresh synthetic subjects were purged in cleanup. Owning-service
  receipts prove declared active-store/linked-history coverage; the rollout did not
  inspect another component's database. Dependency-backed source tests separately
  verify stored session/draft/context removal.
- Linked memory is enabled; gateway and worker both report `2026-11-08.5`.
  Existing users need fresh adult acceptance before new learning/readings. The
  separate external SecondContext knowledge integration remains disabled.
- Telegram authentication and the existing webhook URL were checked without
  registering a new webhook or sending messages. There were zero pending updates
  at the check. This does not establish a new private Telegram conversation.

## Live review boundary

Repository replays use synthetic model replies; the separate live check above uses
the configured provider and synthetic subjects. Private Telegram interaction and
broader model-quality review remain manual Stage 25 work. The [release checklist](../conversation-memory-release.md)
describes that review. No live data, credentials,
generated replies or backup contents belong in this record. The broader Stage 25
MVP checklist remains separate.

## Published images

| Component | Immutable image |
| --- | --- |
| Application `0.2.0` | `quay.io/bdobrica/oria-engine@sha256:066a35b6e7525d0f40323ca6023dd0b4ba10c85e2118e101178173259618757c` |
| Astrology MCP `0.2.0` | `quay.io/bdobrica/oria-astrology-mcp@sha256:347ea24ad7d1fcf4a4d483ad4ba843f176449b5fada9694fbbcf0d8b61bb0ad4` |
| SecondContext `0.2.1` | `quay.io/bdobrica/secondcontext-gateway@sha256:6190173c24ff79094ab7beef24e429b65c55b455a498499cf8dbe4326b9cdf8e` |
