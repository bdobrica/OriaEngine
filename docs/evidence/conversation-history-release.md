# CH7/OCH5 recent-history release — 2026-11-10

Prepared on Oria `d29d7c7` and SecondContext `f0dd2682e215fb72520224509eee04cbf14ba805`.
Provider preparation commit: `9b0d5b45f5f6a17c6b5fbd3b381116ea96448ce3`; Oria CI pins
that exact public checkout for its cross-service gate. Released versions are
Oria application/MCP **0.2.1** and SecondContext gateway **0.2.2**.
The [release checklist](../conversation-history-release.md) is the operational
procedure. **Published and deployed to `oria-live-test`, with recent history enabled.**
Repository defaults remain off. Private Telegram review confirmed policy/deletion but failed conversation continuity;
a correction and retest are required. Decisions/adaptive work remains separately gated.

## Implemented preparation

- Independent bundled provider and Oria capture switches; explicit provider model
  budgets with default-off capture and external `KNOWLEDGE_ENABLED=false`.
  Ingress/workers retain matching disclosure 2026-11-10.1; no consent bypass.
- Synthetic release command using the real Oria adapter and public HTTP only:
  exact capability, local acceptance, optional configured-model recall of random
  codes, accepted replacement replay, identical retries, selective erasure and full
  purge. Fresh synthetic subjects only; no Telegram sends/canonical user mutations.
  Private durable cleanup journal records the fresh UUID before calls, refuses
  overwrites and supports cleanup-only recovery. No transcript/credential output.
- Real-gateway rollback/re-enable tests with pending generated acceptance, lost
  receipt, accepted delivery failure, pending generation cancellation, selective
  erasure and full deletion with both capture switches off. Legacy requests have
  no accepted-history replay or stale linked event context; re-enable preserves
  accepted dialogue and does not backfill intervening legacy dialogue.
- Provider image gate now verifies schema-5 history tables, capabilities, local
  acceptance, process recreation with capture off, receipt retries, rejection of
  new local capture, purge/delayed retries and dirty-migration startup blocking.
  PostgreSQL test readiness uses TCP rather than its temporary bootstrap socket.
- Version publication inputs and both repositories' sequencing/reference docs.
  No application API/schema/ADR changes or new dependencies. Provider local PLAN
  remains outside its implementation commit under its existing convention.

## Verification

- Oria root `make verify` passed: Ruff formatting/lint, strict mypy over 81 source
  files, 14 release-selection tests, **600 unit**, **210 integration**, **391 contract**
  and **13 end-to-end** tests. Two existing upstream TestClient deprecation warnings.
  The local environment uses the existing `/tmp/oria-och2-uv.py` wrapper to execute
  installed `.venv/bin` tools because `uv` is unavailable; no dependencies changed.
- Real cross-service gate: **23 passed** against the reviewed provider source.
  After tightening the smoke script's DTO annotations, its **3 focused cases** passed
  again against installed provider commit `9b0d5b4` (20 other cases deselected).
  `MYPYPATH=src .venv/bin/mypy --strict scripts/check_history_release.py` passed.
- SecondContext root `make verify` passed with real PostgreSQL/Qdrant and no skipped
  mandatory cases, including unchanged OpenAI SDK **3.48.0**. The API history race
  gate passed **12 cases**. `make test-docker` passed the actual packaged-runtime
  migration/capability/rollback/purge gate. Its 14 release-selection tests passed.
- Public schema/fixture comparison passed. Final formatting/lint, diff whitespace
  and **210 local documentation links** checked. No generated schema drift, new
  dependency, credential or private runtime payload was added.

All runtime checks used disposable Oria test projects and synthetic model/Telegram
services. Their resources were removed by scoped cleanup. Sandbox restrictions
required rerunning Docker/loopback checks outside the sandbox. Initial test assertions
were corrected for JSON whitespace in saved receipts and legacy generation without
replay; pending erasure still excludes stale event context. No production behavior
was weakened to make those assertions pass.

## Publication and live rollout

- Provider source `9b0d5b45f5f6a17c6b5fbd3b381116ea96448ce3` passed
  [CI and packaging](https://github.com/bdobrica/SecondContext/actions/runs/42763889495)
  and [publication](https://github.com/bdobrica/SecondContext/actions/runs/42763889444).
- Oria source `6439c6f1ed02d4ef49403f27cbb129a1ead00384` passed
  [aggregate and cross-service CI](https://github.com/bdobrica/OriaEngine/actions/runs/42763892673)
  and [both image publications](https://github.com/bdobrica/OriaEngine/actions/runs/42763892638).
- All selected manifest indexes contain linux/amd64 and linux/arm64 images.
  Pulled host images' OCI source/version labels match the exact release commits.
  Immutable digests below match running gateway, worker, MCP and provider images.
- Only `oria-live-test` was maintained. Prior releases were Oria/MCP 0.2.0 and
  SecondContext 0.2.1. Images were pulled/verified before callers were drained.
  Separate owning-role database dumps and a cold Qdrant archive were created under
  private operator storage, along with the existing env/key configuration. Archive
  structure was checked; a backup restore was not exercised. No unrelated resources
  or live volumes were removed; no host-wide prune.
- The owner's migration executable reports SecondContext **version 5, dirty=false**;
  Oria's migration command reports **0013 (head)**. No schema downgrade was attempted.
- The released worker adapter passed `check_linked_release.py --generate` against
  actual MCP/SecondContext/model services: calculated tools, scoped projections,
  generation, correction, stale-reference rejection, selective erase and full purge.
- `check_history_release.py --generate` passed against the configured real model:
  it recalled two fresh random synthetic codes, first from local dialogue and then
  from an accepted replacement. Identical generation/finalization retries converged;
  whole linked-session erasure and full purge fenced delayed retries. All fresh
  synthetic subjects were purged and their private cleanup journals removed.
- A separate live provider rollback drill prepared a local accepted exchange and
  pending generated draft, then recreated the provider with capture disabled while
  Oria callers stayed stopped/capture-off. Ready discovery and new local capture
  were unavailable; the existing local receipt and pending generated acceptance
  still finalized exactly. Legacy generation worked. Selective erasure and full
  purge rejected delayed writes. Restoring provider capture restored recent-only
  capability. The drill did not send Telegram messages; consumer delivery behavior
  is covered by the real-gateway synthetic tests above, not a live delivery claim.
- Oria capture was then enabled and gateway/worker restarted on matching images.
  Both use disclosure **2026-11-10.1** and require fresh acceptance. Provider capture
  and linked projections are enabled; external `KNOWLEDGE_ENABLED=false` remains.
  Application services are healthy and private gateway readiness passed.
- Telegram's existing webhook URL/update types were verified without changing
  registration or sending messages; pending updates were **0** at that check.
  Existing private settings (including credentials, encryption key, model and
  namespace) were compared against the backup and preserved. `deploy/.env` remains
  mode **0600**. No private payload, credential or journal is committed here.

| Component | Published immutable image |
| --- | --- |
| Oria application 0.2.1 | `quay.io/bdobrica/oria-engine@sha256:5fc4ce8b9265f16e6d264faeb5a5150dfefe41b91fbb6cb478dd513fd43cd255` |
| Astrology MCP 0.2.1 | `quay.io/bdobrica/oria-astrology-mcp@sha256:00953d1f67836dde5386ccca483d47b7c6007e08a77439956f429286e637abb4` |
| SecondContext 0.2.2 | `quay.io/bdobrica/secondcontext-gateway@sha256:180478c974b5529f074187317bf44f0f372f414fae6a03bb43926561ac1f7557` |

## Remaining review

The participating user confirmed fresh policy acceptance and account deletion.
Conversation review failed: the first reading was not available to a follow-up,
a later response showed only a snapshot label, and a subsequent request received
no reply. Read-only, content-free live metadata showed a terminal
`context_budget_exceeded` event with no current queue barrier. The snapshot-only
symptom has not yet been independently reproduced. No private transcript or account
identifier is retained here. Do not mark the conversation gate complete until retested.
Erasure receipts establish active-store coverage, not removal from Telegram,
backups or upstream provider retention.

CH4–CH6 remain unimplemented: Decisions observation, cache economics and adaptive
selection are unsupported. This release establishes recent-history continuity and
provider capture rollback, not adaptive-to-recent rollback or broad model-quality
review. The wider Stage 25 MVP gate remains separate.

## Conversation correction — Oria 0.2.2

The first-reading regression was reproduced with a freshly confirmed synthetic
profile and no fixture-side projection flush: the reading was sent locally, with
zero generation or acceptance calls. The worker now stages existing canonical
sources in a committed transaction and attempts bounded projection delivery before
preparing an ordinary new turn. Source outage/backoff retains the documented local
fallback, and frozen retries, private clarification and controls skip the preflight.

The bundled input budget increases from 32,768 to 65,536 conservative units, with
4,096 output tokens reserved. The real-gateway regression includes current natal
and transit facts, a follow-up, another daily-reading request and an explicit date.
Its largest model request exceeds the old budget and fits the new budget. It checks
that the first accepted reply is present in the follow-up's actual model input.

Verification: `make verify` passed (600 unit, 212 integration, 391 contract and
13 end-to-end tests; Ruff, strict mypy and 14 release-selection tests). The full
cross-service gate passed 24 tests using the real provider and synthetic model.
The strengthened profile-edit case also passed separately, proving automatic source
delivery, old-session fencing and fresh calculations without a fixture-side flush.
The app patch is version 0.2.2; MCP stays 0.2.1 and SecondContext stays 0.2.2.
No schema, disclosure, credential or provider runtime change was required.

Patch source `cedda0082470ba0e24a9a549e8deeaa7f93ee5bc` passed
[aggregate and cross-service CI](https://github.com/bdobrica/OriaEngine/actions/runs/42895995197)
and [app publication](https://github.com/bdobrica/OriaEngine/actions/runs/42895995379).
The deployed app digest is
`quay.io/bdobrica/oria-engine@sha256:7fb61db9b75472612c193bb46a932c5e1818c459d0fe3d81c644d3fa9e8b7a7a`.
Both platform manifests and the pulled source/version labels were verified.

The patch was deployed only to `oria-live-test`. Callers were drained, and owning
Oria metadata confirmed zero unresolved history/ingress work before changing the
provider budget. Fresh owning-role database dumps, a cold Qdrant archive and private
configuration backup were structurally checked; restore was not exercised. No
migration was applied: Oria remains 0013 and SecondContext 5 clean. The only private
configuration changes were the app image and input budget; other settings were
compared against the protected backup. Gateway and worker run the same app image.

The released adapter passed live-model random-code recall, accepted replacement,
selective erasure and full purge. A second fresh synthetic subject used actual MCP
natal/transit facts for four managed turns: daily reading, follow-up with a marker
available only in accepted history, another daily reading and an explicit date.
All generated substantive text and received ordered acceptance receipts. Both
synthetic subjects were purged and their private cleanup journals cleared. These
checks sent no Telegram messages and read no real account payloads.

All application services were healthy afterward; gateway readiness and unchanged
Telegram webhook registration passed, with zero pending updates at inspection.
The participating user has been asked to repeat the private conversation sequence.
That retest remains pending, including the previously unreproduced snapshot-only
symptom. The application still terminalizes nonretryable provider errors; the failed
old input was not resurrected or assigned a new turn ID.
