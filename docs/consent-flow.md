# Deterministic consent flow

`domain.consent.ConsentFlow` implements PLAN sections 5.1–5.2 and 13 using the
existing [identity and consent repositories](identity-consent.md). Consent decisions
use no LLM; the [worker](worker-queue.md) supplies its transaction and Redis coordination. Each update resolves trusted
channel identifiers to the internal user UUID and reads/writes consent inside one
transaction. Replies are sent after commit so delivery failure cannot undo a decision.

## Disclosure and decisions

The initial copy is `DISCLAIMER` in `domain/consent.py`, using
`ORIA_POLICY_VERSION` (default `2026-10-03`). It covers AI identity, interpretive
astrology, high-stakes limitations, birth date/time/place, chart purpose and future
storage, prohibited unrelated PII, planned profile/edit/delete controls, and adult
use. **I'm 18+ and agree** confirms adulthood and acceptance together; it is a
self-attestation, not age verification. The copy explicitly describes this demo's
limits: encrypted birth profiles and drafts are collected, local place lookup and
time clarification and calculation are available, deletion remains unavailable,
and prior data remains after decline. `/privacy` shows the
disclosure and the same decision buttons. The Stage 16 disclosure also covers
SecondContext and AI-provider processing, retained filtered messages/replies/context,
facts quoted in replies, limited filtering, blocked drafts and deletion limitations.
See [conversation worker](conversation-worker.md).

Keep each deployed version associated with its disclosure in source history. Bump
`ORIA_POLICY_VERSION` when the copy/data use changes and deploy consistently to all
ingress processes. Changing copy without bumping the version does not invalidate
existing database acceptances. The button fingerprint hashes both the version and
copy, so buttons from another version/copy cannot record a current decision. It is
a bounded routing identifier, not an authentication token; ownership always comes
from the transport sender. Unknown/stale buttons redisplay current policy and
leave the stored decision unchanged. Free text (including “yes”, “I agree”, birth
details or pasted callback data) never grants consent.

| Durable latest decision for configured policy | Resolved state | Behavior |
| --- | --- | --- |
| None, or a different policy version | `ConsentRequired` | Disclosure and buttons |
| Accepted | Resolved from profile/draft completeness | Start or resume deterministic onboarding |
| Declined or revoked | `Closed` | Stop onboarding; `/start` can reoffer disclosure |

Accept and Decline append versioned lifecycle records, including timestamps and
channel. Repeating the same decision consecutively is idempotent. Decline after
acceptance removes current consent. `/start` and `/privacy` only change what is
displayed; they never grant consent or erase a decline. A new configured policy
requires a fresh acceptance even after a previous decline or acceptance.

## Scope and continuation

Before consent, the Telegram ingress discards free text. After consent, input and
pending replies are temporarily encrypted under the [queue retention rules](worker-queue.md). After consent, [onboarding](onboarding.md)
stores strict encrypted drafts and confirmed [birth profiles](birth-profiles.md),
with current-consent checks under the user lock for every write.
[Derived-profile activation](astrology-profiles.md) retains that check. Full profile
display, expanded privacy controls and deletion remain stages 17–18. `ConsentFlow` without an injected onboarding handler
retains the consent-only paused response for isolated use/tests; the worker wires the
onboarding handler and requires encryption configuration.

The inbound-event UUID anchors durable update deduplication, so delayed replay of
an old update cannot repeat its decision. A fresh click is a new update and may
change a same-policy decision. Domain transitions and pending replies commit together;
Telegram delivery remains at least once across an ambiguous send/crash boundary.

## Verification

`tests/integration/test_consent_flow.py` exercises first contact and unsolicited
text, explicit decisions and timestamps, restart via a fresh flow instance,
sender isolation, policy changes and stale buttons, deleted users, and the complete
dispatcher-to-database path with failed delivery. Existing repository subprocess
tests verify consent survives process restarts. Unit tests replay Telegram callbacks,
reject unsupported ownership/chat contexts, check acknowledgement and keyboards,
and verify privacy-safe logging and polling resource cleanup.

Run `make verify`. See the [manual consent smoke test](telegram.md) for live validation.
