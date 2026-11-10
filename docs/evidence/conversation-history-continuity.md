# OCH4: Cross-service conversation continuity

Synthetic validation of the real Oria worker/adapter against SecondContext CH3
commit `f0dd2682e215fb72520224509eee04cbf14ba805`. This is a reproducible compatibility
gate, not a deployment, paid-provider evaluation or Telegram review. The companion
CI job pins that provider revision.

## Reproduction and isolation

With Oria development dependencies, Go matching the provider's `go.mod`, and Docker
Compose available:

```sh
SECOND_CONTEXT_SOURCE=/path/to/SecondContext make test-history
make verify
```

`test-history` fails if the checkout, toolchain, dependencies, migrations or service
capabilities are unavailable; it does not silently skip. Normal `make verify`
remains independent of a sibling checkout. CI runs both gates separately. Update
the pinned provider deliberately when adopting a newer compatible implementation.

The harness builds public `cmd/api` and `cmd/migrate` executables in a temporary
directory and applies migrations using the owning executable. It compares the
public schema/fixtures before exercising the boundary. Oria uses only authenticated
versioned HTTP; it never imports provider internal types or accesses its database.
Oria's PostgreSQL/Redis and the provider's PostgreSQL/Qdrant use separate random
disposable Compose projects, ephemeral loopback ports and generated credentials.
Teardown addresses only those projects. No live configuration, storage or `.env`
files are used.

The real gateway calls a loopback synthetic model endpoint that records model
messages in memory and returns deterministic text. An HTTP transport forwards real
gateway calls, injecting selected failures before dispatch or after receiving the
actual response. Killing/restarting the gateway exercises durable provider state;
resetting an Oria worker exercises encrypted consumer recovery. The harness does
not implement replay or fabricate finalization/erasure acknowledgements.

## Assertions

| Area | Evidence |
| --- | --- |
| Follow-ups, options, corrections, topic changes | Exact ordered model dialogue, including only the newest eight complete exchanges; recent mode retains dialogue on topic change |
| Current facts | One current system message contains exact prepared Oria instructions and the provider's historical-dialogue boundary; old instructions are not replayed as messages |
| Isolation | New sessions under the same subject and a separate subject receive no first-conversation dialogue |
| Replacement | The next turn contains Oria's accepted replacement, never the rejected draft |
| Duplicates/order | Concurrent duplicate ingress generates once; later events wait for delivery resolution without consuming attempts |
| Lost acknowledgements | Actual persisted result/receipt retries use the same body across gateway/worker restarts and interrupted recovery; accepted text appears once |
| Generation crash | A killed gateway leaves a resumable reservation; another provider execution is allowed with the same model input and one accepted exchange |
| Delivery | Exhaustion preserves known rejection versus ambiguity; accepted text replays with current instructions that delivery is unconfirmed |
| Local exchanges | An explicit local question and actual deterministic calculated reading use worker acceptance and replay in order; calculated text has source links |
| Withdrawal | Privacy bypass, cancellation/wipe and real draft abandonment; reacceptance retains accepted history but never revives canceled input |
| Expiry/disablement | Local envelope expiry wipes input and abandons the remote draft with capture disabled; expired exchanges never replay |
| Correction | Pending source changes suppress generation; acknowledged revision changes fence old acceptance, rotate sessions and supply recalculated natal facts |
| Selective erasure | Pending local deletion suppresses replay before remote acknowledgement; recovery/restart preserve the session fence against delayed acceptance |
| Full purge | Actual Oria deletion worker removes local work, obtains real subject-purge acknowledgement and completes; delayed acceptance hits the subject fence |

The local-question test supplies a synthetic explicit conversational branch through
`capture_local`; it does not claim every production clarification is eligible.
OCH3 tests retain detailed exclusions, rollback, encryption, receipt validation,
admission and cleanup checks. Provider-owned CH3 tests cover storage-level cleanup
and races; this gate proves observable HTTP behavior without inspecting its tables.

## Defects found and corrected

Managed Responses echoes the subject directly in `metadata.user_external_id`;
Oria previously expected only the legacy nested context-packet echo. Managed
validation now accepts either form, requires at least one, and rejects missing,
malformed or conflicting supplied echoes. Legacy validation remains unchanged.
Contract tests exercise both forms and conflicts; identity checks remain mandatory.

The time-unit hint treated “the second one” as an incomplete time request. Option
references now remain follow-ups, while “in one second” and “two seconds ago” still
resolve against ingress. Informal conversational corrections such as “Actually,
I meant the first option” previously requested a saved-record correction. Without
a selected/named record, date or field-edit cue, they now continue to dialogue.
Real canonical corrections retain their local behavior.

Disposable PostgreSQL health checks now use TCP, matching the test clients. This
avoids reporting readiness during the image's temporary Unix-socket bootstrap
server, which produced intermittent migration connection resets during validation.

## Verification

Validated on 2026-11-10:

- `make test-history`: **14 passed**, 56.63 seconds, using the real provider revision
  above; public schema/fixture comparison also passed.
- Focused adapter/active-routing/relative-time tests: **244 passed**. The new focused
  canonical-memory regression passed, followed by the full integration gate below.
- `make verify`: **passed** in one final aggregate invocation: Ruff formatting
  (261 files), Ruff lint, strict mypy (81 source files), **14 release unittests**,
  **600 unit**, **210 integration**, **389 contract**, and **13 end-to-end** pytest
  cases. Two existing Starlette/AnyIO deprecation warnings remain. Total: **1,212**
  ordinary pytest cases, plus **14** cross-service cases.
- SecondContext `make test-unit` (`go test -short ./...`): passed. This intentionally
  excludes its dependency-backed suites; no claim of running its full `make verify`.
- Default pytest collection: **1,212** cases without a provider checkout requirement.
  Final diff/format/lint and public snapshot checks passed; **154** local documentation
  links resolved. No generated schema drift or provider source changes.

Local Make invocations used the installed `.venv` through a temporary `UV` launcher
because `uv` was unavailable, and added `/usr/local/go/bin` to PATH for the provider
build. No dependency installation is claimed. GitHub Actions was configured but
not remotely executed. Early runs exposed the three runtime defects above and
fixture readiness/assertion issues; final gates include their corrections.

No paid/live model, real Telegram delivery, publication, live migration or deployment
was performed. Deterministic replies prove context assembly and lifecycle, not model
quality. OCH5/CH7 own release/live checks; Decisions/cache/adaptive evaluation stays
inside SecondContext CH4–CH6. History defaults off; external `KNOWLEDGE_ENABLED`
stays disabled.
