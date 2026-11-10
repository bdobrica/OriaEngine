# CH7/OCH5 release preparation — 2026-11-10

Prepared on Oria `d29d7c7` and SecondContext `f0dd2682e215fb72520224509eee04cbf14ba805`.
Provider preparation commit: `9b0d5b45f5f6a17c6b5fbd3b381116ea96448ce3`; Oria CI pins
that exact public checkout for its cross-service gate. Candidates are Oria application/MCP **0.2.1** and SecondContext gateway **0.2.2**.
The [release checklist](../conversation-history-release.md) is the operational
procedure. **Publication and live rollout are pending**; no candidate digest has
been selected and history remains default off. This record is not a live release
receipt or completion of all CH7/OCH5 tasks.

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

## Operational boundary

Read-only inspection found the existing `oria-live-test` services running their
prior pinned digests: Oria/MCP 0.2.0 at `c4e142953ade5fcdc40d08af09babefa1dc66ca6`,
SecondContext 0.2.1 at `683fa7e83512afa0172e79f14f38c31a2c61d47a`.
Latest visible Oria GitHub runs were for OCH1 `78fde01`, before
OCH2–OCH4; their success is not validation/publication of these candidates.
No live environment, images, databases, key, bot/webhook, disclosure or capture
setting was changed. No push, Quay publication, live migration, paid-provider call,
private Telegram review or live rollback drill was performed in this preparation.

Before declaring CH7/OCH5 released: publish and verify exact revisions/digests,
follow owning backup/migration steps, run both release scripts against the selected
images, deploy consistent consent and enable recent history, validate an explicitly
participating private Telegram test account, then record the live rollback drill.
CH4–CH6 are unimplemented, so Decisions observation and adaptive selection remain
unsupported. Synthetic results do not establish provider quality, Telegram delivery,
upstream erasure or live behavior.
