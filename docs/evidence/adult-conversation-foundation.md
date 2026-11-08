# Adult conversation and knowledge-contract foundation

Validated 2026-11-08 with synthetic data and isolated Oria test resources.

## Implemented behavior

Product policy `oria-policy-4`, methodology `oria-methodology-4` and context
guidance permit useful voluntary personal context and sensitive discussion.
Narrow English checks replace topic-wide rejection with checks for explicit
harmful requests/directions, unnecessary identifier solicitation, selected
unsupported claims and false storage/edit/forget acknowledgements. No recurring
professional-support reminder is required. Consent and application authority
remain independent of model output.

Recognized birth-bearing messages use a value-free conversational fallback rather
than the former privacy refusal or implicit transit/profile edit. The worker and
application service retain the local birth-input boundary. This is coarse
withholding, not structured event extraction or a calculated compatibility rating.
Obvious secrets remain local; ordinary volunteered identifiers are allowed in chat.

Consent version `2026-11-08.1` discloses this processing and its current limitations.
Application defaults, example configuration and Compose defaults agree; ingress
and worker startup reject the known previous disclosure versions. Custom versions
still require an operator bump before deployment.

[ADR 0002](../adr/0002-private-life-events-and-context-projections.md) establishes
canonical Oria records and scoped SecondContext projections. The generated
[candidate contracts](../../contracts/knowledge/v1.md) cover temporal precision,
entities/events, revisioned projection operations and scoped acknowledgements.
They add no live routes or storage. SecondContext's current owning contract was
inspected: its service credentials authorize only response, fixed memory ingest
and subject purge. The proposed lifecycle requires owning-service acceptance and
implementation before use.

## Verification

The final `make verify` completed successfully using the installed virtual
environment through a thin `uv run` shim (the `uv` executable was unavailable):

- Ruff format/lint: 203 files; mypy: 64 source files.
- Release-selection tests: 14 passed.
- Unit tests: 484 passed.
- Integration tests: 127 passed.
- Contract tests: 164 passed, including both container workflows.
- Telegram replay E2E tests: 11 passed.

Total: 800 automated tests passed. The unit lane emitted two existing upstream
TestClient deprecation warnings. Both schema generators passed `--check`;
repository-local documentation links and `git diff --check` were checked.

Coverage includes benign sensitive topics, relevant entity questions, partner
birthday withholding, harmful requests mixed with birth details, current consent,
account isolation, no implicit profile changes, strict acknowledgement scope and
candidate schema drift. Existing astrology contracts, migrations and dependencies
are unchanged.

No live model/Telegram generation, deployment or upstream knowledge-lifecycle
implementation was performed. Lexical checks and synthetic replies do not prove
semantic safety or real-model compliance. Natural-time extraction, event storage,
linked recall/selective erasure and partner calculations remain subsequent slices.
