# Linked context implementation verification

Date: 2026-11-08. This is source verification, not publication or a live rollout.
Owning-service implementation: SecondContext local commit
`287e201758c313b4e9b8f4b3aef675a9c5dc2ce5` (`linked-context-1`).
[Linked context](../linked-context.md) documents behavior and limits;
[ADR 0002](../adr/0002-private-life-events-and-context-projections.md) preserves ownership.

## Scope

Oria migration `0012` adds encrypted desired projection work and content-free retry
state. Optional `linked-context-1` HTTP integration adds canonical summaries,
participant links, user-stated significance, filtered prior interpretations and
bounded retrieval with current owner/source checks. Canonical data stays in Oria.
SecondContext migration `000004` adds its separate indexed projection/operation/link
lane, terminal record fences and linked-session erasure under its ADR 0006.
Disclosure `2026-11-08.4` covers the expanded data use; the feature defaults off.
No accepted Oria ADR, astrology schema, external dependency or private configuration
was changed. No live MVP migration, image update, container cleanup or deployment
was performed. All container work used identified isolated Oria test projects.

## Verification

The root `make verify UV='/bin/sh /tmp/oria-existing-venv.sh'` gate passed using
the installed virtual environment: formatting/lint, mypy (73 source files), 14
release checks, 575 unit, 164 integration, 174 contract and 11 end-to-end tests.
The normal `uv` executable was unavailable, so the wrapper ran the Makefile commands
through the existing environment. The seven focused regressions (six linked-memory cases plus seeded account erasure)
also passed, and those cases are included in the final full gate.
Both schema generators passed `--check`; no astrology schema drift occurred.
Repository-local Markdown targets and final whitespace/static checks passed.

- Focused Oria projection lifecycle tests: six passed with isolated PostgreSQL/Redis.
  They cover post-commit delivery, encrypted payloads, birth values withheld from
  projection requests, interpretation retrieval, corrections, importance overrides,
  opt-out, stale/altered retrieval, pending erasure, withdrawal/disablement and
  natal-profile revision invalidation with explicit own-birthday lookup.
- Projection content/HTTP/knowledge contract tests: 63 passed, including every
  house theme, raw input withholding, strict receipt scope/revision/coverage and
  unchanged-operation retries after an ambiguous response.
- SecondContext `make fmt-check vet test-unit` and its mandatory dependency-backed
  integration suite passed in the owning-service source. New cases cover idempotency,
  conflicting writes, owner isolation, source corrections, latest explicit salience,
  retained linked-session/draft/context erasure, failure fences and restart recovery,
  denied resurrection, unknown-ID erasure and full-subject purge.
- Oria's actual Python HTTP adapter against the built SecondContext gateway binary
  and isolated PostgreSQL/Qdrant passed capabilities, repeated upsert/query/delete,
  denied high-revision resurrection and full-subject purge. This wire/storage check
  used no mock HTTP service and made no OpenAI or Telegram generation calls.

SecondContext's existing integration script is tracked without an executable bit;
its `make verify` invocation fails at that script. The equivalent component gates
were run explicitly, invoking the script with Bash. No unrelated workflow fix is
included. The owning service records details in `docs/evidence/linked-context-v1.md`.

No live-provider generation, private Telegram exchange, production erasure, image
publication or rollout is claimed. Projection retrieval and generation tests are
synthetic; generation uses a fake provider. Full release validation remains slice 6.
