# Natural-date routing and temporary clarification

Verified 2026-11-08 with synthetic data and isolated Oria test services. Implements
slice 2 of the [delivery sequence](../conversation-memory-plan.md#delivery-sequence-and-acceptance).
The [behavior reference](../current-time.md) documents English/Gregorian grammar,
precision, sampling conventions and limits.

## Delivered boundaries

- Typed temporal roles separate event narratives, birth inputs, anniversaries,
  own-profile corrections and calculation targets. Multiple event dates/clocks do
  not implicitly authorize transits or mutate the natal profile.
- Absolute/relative/mixed dates, elapsed versus calendar offsets, partial and
  approximate dates, ranges and supplied event anchors retain precision. Leap-day
  anniversaries ask about observance; ambiguous DST clocks require clarification.
- Migration `0010` adds encrypted, owner-scoped pending date questions with original
  ingress reference, consent binding, timezone provenance and local anchors. Replies
  resume after restart; retries do not move the reference. Expiry, withdrawal,
  explicit profile editing and confirmed account deletion clear temporary state.
- Birth clauses and obvious continuations stay local, including their resolved
  temporal values. Non-birth values are untrusted user-stated context. An explicit
  own-birthday reference can read the user's local encrypted profile; another
  entity's input never selects another account.
- Consent `2026-11-08.2`, policy `oria-policy-5` and methodology
  `oria-methodology-5` describe current capabilities. Event-profile memory,
  selective forgetting, partner calculations and new SecondContext routes remain
  unavailable. Existing astrology/knowledge JSON schemas and dependencies did not
  change.

## Verification performed

The documented aggregate command passed using the already installed environment:

```sh
make verify UV='/bin/sh /tmp/oria-existing-venv.sh'
```

The shim only dispatches `uv run` commands to the existing `.venv`; it does not
change dependencies. Container/threaded lanes ran outside the filesystem sandbox.
The full gate passed 529 unit tests. After adding two birth-continuation routing
regressions, the unit and integration lanes were rerun on the final code:

```sh
make test-unit test-integration UV='/bin/sh /tmp/oria-existing-venv.sh'
```

Latest passing results by lane:

| Lane | Result |
| --- | --- |
| Ruff format/lint | 210 Python files checked |
| Strict mypy | 67 source files checked |
| Release selection | 14 passed |
| Unit | 531 passed; two existing upstream TestClient deprecation warnings |
| Integration | 138 passed |
| Contract | 164 passed, including development and image-deployment stacks |
| E2E | 11 passed |

Both schema generators passed `--check`; `git diff --check` passed. Migration tests
covered empty/repeated upgrade, metadata consistency and downgrade/re-upgrade.
Synthetic coverage includes the design's date examples, multiple roles/clocks,
calendar clamping, leap/DST ambiguity, timezone overrides, birth withholding,
clarification after restart, choice of relative target across midnight, downstream
retry, owner isolation, expiry, withdrawal, no-retention intent and account deletion.

## Verification limits

No live model/provider, private Telegram conversation, published release or MVP
deployment was verified or changed. Isolated Oria test resources were used; private
deployment configuration and unrelated projects were untouched. No long-term
event/entity storage, remote projection lifecycle or new calculation capability
was enabled. The English parser and birth/secret filtering are bounded rules,
not unrestricted language understanding or proof of model compliance.
