# OCH3 durable conversation history workflow

Date: 2026-11-10. Scope: Oria consumer implementation of
[ADR 0003](../adr/0003-accepted-conversation-history.md), following the OCH2 adapter.
SecondContext's public schema/fixtures are unchanged; no provider implementation
files were changed. Runtime integration uses only the versioned HTTP boundary.

## Implemented behavior

Migration `0013` adds encrypted transient prepared/finalize work, payload-free exact
receipts and independent delivery state. Preparation rolls back domain side effects
before freezing the request; accepted replies and finalization work then commit
atomically with domain state. Provider generation retries use the frozen body,
finalization retries use the saved acceptance, and channel retries use the saved
reply. Five attempts and the original 24-hour event expiry cover all stages.

Privacy controls bypass a blocked ordinary head while preserving owner serialization.
A bounded answer gains that bypass only for an actual pending inspection/erasure
choice, not ordinary conversation focus. Managed ingress binds the consent revision;
withdrawal wipes even unattempted managed inputs. Cancellation, source correction,
erasure, policy change and disablement cannot revive canceled work. Minimal
abandonment recovery runs without Redis or capture enablement; accepted/ambiguous
outcomes are never misreported as failed or successfully abandoned.

Current acknowledged canonical source links gate capture; profile correction rotates
the session only after cancellation/cleanup and source acknowledgement. Full deletion
cancels history at confirmation and removes its owner rows before the existing subject
purge. Guarded replacements and final application labels are the accepted text.
Deterministic local readings use the same lane; private inputs, controls, clarification,
mutation receipts and status/error exchanges remain uncaptured.

`SECOND_CONTEXT_HISTORY_ENABLED` defaults off and requires linked memory. Disclosure
`2026-11-10.1` covers replay/local exchanges, accepted but undelivered replies, retention,
erasure and optional Decisions processing. Both ingress and worker reject the old
built-in version; custom versions must also change. See the [workflow reference](../conversation-history.md).

## Verification

Focused tests use synthetic HTTP responses and real isolated PostgreSQL/Redis. They
cover durable preparation before HTTP, atomic reply/finalize staging, rollback,
restart and exact retries, wrong receipts, replaced drafts, source readiness/revision
change, terminal/ambiguous delivery, consent withdrawal/reacceptance, privacy bypass,
capture disablement, expiry/abandonment, local capture, full-deletion cancellation
and authenticated-encryption bindings. Shared schema/fixture comparison is unchanged.

Focused workflow suite: **33 passed** (`tests/integration/test_history_workflow.py`).
A prior combined workflow/migration run passed 23 cases; migration upgrade/repeat,
downgrade and metadata checks are also part of the aggregate gate. Schema/fixture
comparison against the sibling public contract passed. New documentation links and
`git diff --check` passed.

All required verification lanes passed after the affected fixture reruns:

| Check | Result |
| --- | --- |
| Ruff formatting/lint | Passed; 257 Python files formatted consistently |
| Strict mypy | Passed; 81 source files |
| Release selection unittest | 14 passed |
| Unit pytest | 595 passed (two existing framework deprecation warnings) |
| Integration pytest | 209 passed, including 33 OCH3 workflow cases and migration checks |
| Contract pytest | All 379 cases covered successfully; see rerun detail below |
| E2E pytest | 13 passed |

This covers **1,196 pytest cases** plus 14 release checks. The aggregate was invoked
with `make verify UV='python3 /tmp/oria-och2-uv.py'`. `uv` was unavailable on PATH;
the temporary shim maps `uv run <tool>` to the existing `.venv/bin/<tool>` without
changing Makefile targets or installing dependencies. No `uv sync` was claimed.

The final aggregate invocation passed lint, types, release checks, unit/integration
and 378 contract cases, then found a deployment fixture missing the newly added
history environment key. After correcting that fixture,
`pytest tests/contract/test_image_deployment.py -q` passed all 18 affected cases
(including the previously failing case), and `make test-e2e` passed all 13 replays.
These targeted reruns complete the aggregate's required checks; this is not a claim
that the initial aggregate invocation exited successfully.

An earlier run also exposed an existing date-test fixture whose synthetic “yesterday
at 23:30” reference expired when tests ran after 23:30 UTC. Its reference now remains
live while the synthetic reply still crosses midnight. The focused date test and
subsequent full integration lane passed; production retention/resolution was unchanged.
The new managed fallback gives the calculated reading without repeating the legacy
renderer's general disclaimer.

Additional checks verified default-off configuration and its linked-lifecycle
prerequisite, physical removal of history rows during local account deletion, and
conservative cancellation-ID expiry (24 hours plus the bounded 60-second call-start
allowance; sensitive payload retention never extends). All disposable test-stack
teardowns completed. No live storage or unrelated projects were modified.

## Limits

No live SecondContext/model/Telegram run, paid provider call, publication, deployment,
live migration or feature enablement was performed. The provider was simulated at
the versioned HTTP boundary; these results do not establish real-service prompt
replay or model quality. OCH4 cross-repository continuity checks and OCH5 coordinated
release remain pending. Legacy behavior remains available by configuration. No new
dependency, public wire-schema change, automatic memory extraction or exactly-once
provider/channel guarantee is introduced.
