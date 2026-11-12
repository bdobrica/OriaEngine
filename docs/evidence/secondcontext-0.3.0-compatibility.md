# SecondContext 0.3.0 compatibility check — 2026-11-12

**Deployment blocked; `oria-live-test` remains on SecondContext 0.2.3.**
The 0.3.0 memory-command response path omits the subject echo required by Oria's
existing adapter. No live image reference, setting, schema or storage was changed.

## Candidate and baseline

| Component | Version | Source revision |
| --- | --- | --- |
| Running Oria | 0.2.4 | `167f7c6296ab04dbb943e74a85c303421ce81f8e` |
| Running SecondContext | 0.2.3 | `98328e1139e76ed93a62543caa537f6a632443eb` |
| Candidate SecondContext | 0.3.0 | `d8d938cdb811f5de840f54b9173988a07b7ccfc9` |

Candidate immutable image:
`quay.io/bdobrica/secondcontext-gateway@sha256:37d87c1c958926bd3d9b4f8c5ee12eeff7137e350217f0600e56c2ae36542639`.
Both `0.3.0` and `latest` resolved to that digest. The pulled host image's
source/version/revision labels match the candidate. Its
[verification](https://github.com/bdobrica/SecondContext/actions/runs/43296425973)
and [publication](https://github.com/bdobrica/SecondContext/actions/runs/43296425904)
completed successfully.

History schema/example snapshots match byte-for-byte. The candidate requires
provider migrations 000006–000009 and changes the managed-history configuration
recipe; a future rollout must resolve pending old-recipe work before switching.
Conversational learning remains separately opt-in; publishing this release does
not enable it. External knowledge, observation and adaptive selection remain off
in the existing deployment.

## Blocking reproduction

The new [scope regression](../../tests/cross_service/test_provider_scope_compatibility.py)
sends three prepared turns through Oria's real HTTP adapter to the owning gateway,
with synthetic subjects and model responses:

| Input | SecondContext 0.2.3 | SecondContext 0.3.0 |
| --- | --- | --- |
| `Suggest a quiet activity` | Passed | Passed |
| `Pause learning` | Passed | Invalid conversation history response |
| `Can you show my memories?` | Passed | Invalid conversation history response |

In the candidate, `buildResponseContext` returns `commandPacket()` before filling
`UserExternalID`. Managed Responses includes that packet alongside the direct
subject echo. Oria validates every supplied subject echo; the missing nested echo
causes `ContextUnavailable`. This is a response-validation failure, not evidence
of another account's data being exposed. Legacy Responses also relies on the
nested echo, although this focused regression exercises managed Responses only.

The provider should populate the authenticated subject consistently on its command
response path. Do not relax Oria's account-scope validation to accept the omission.
After a compatible provider release, rerun the cross-service gate and the
[coordinated rollout checks](../conversation-history-release.md).

## Executed verification

- Candidate source at the exact published revision: existing `make test-history`
  suite **7 passed, 20 failed**. Many failures are model-call-count assertions:
  CL2 adds interpretation calls that the older recorder treats as generation.
  Those failures alone do not establish broken history or erasure. The fixture
  needs to distinguish interpretation from generation before certifying CL2.
- Candidate focused subject-scope regression: **1 passed, 2 failed**, independently
  reproducing the response-validation blocker without model-call-count assertions.
- Current provider release, extracted from its immutable source revision:
  `make test-history`, including the new regression, **30 passed**.
- Contract snapshot check, `make lint typecheck` and `git diff --check` passed.
  The Make targets used the existing Python environment through the local wrapper;
  `uv` was unavailable on the command PATH. Go used the installed toolchain.
- Live services remained healthy; SecondContext's owning migration command reports
  `version=5 dirty=false`.

These tests compiled each exact provider source revision and used isolated real
PostgreSQL/Qdrant and HTTP transport with synthetic model/Telegram services. They
did not run the candidate container against live storage. No live-provider
generation, live erasure, Telegram send, migration, backup or rollout was attempted
after the compatibility failure. The unrelated full `make verify` lanes were not
rerun for this test/documentation-only change; the complete cross-service gate and
repository static checks were run.
