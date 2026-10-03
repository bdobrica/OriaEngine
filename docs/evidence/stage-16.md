# Stage 16 verification

Implementation date: 2026-10-03. Scope: existing queued consent/onboarding path
through active astrology facts, SecondContext, application policy and Telegram
delivery. See [runtime reference](../conversation-worker.md).

## Deterministic verification

Focused privacy checks passed (18 tests). The initial integration run exposed a
test-fixture teardown omission: conversation-session rows now exist and must be
removed before users. After correcting cleanup, the original nine pipeline tests
passed. Expanded checks cover unknown/approximate time, withdrawal before queued
processing, and the actual HTTP adapter against a scoped stub. The latter first
rejected a test setup lacking a service credential; a synthetic token fixes setup
without weakening configuration validation.

`make verify` completed successfully:

- Ruff formatting (129 files) and lint passed.
- Strict mypy passed (53 source files).
- Unit tests: 277 passed (37.49 seconds).
- Integration tests: 81 passed (393.51 seconds), using isolated PostgreSQL/Redis.
- Contract tests: 82 passed (50.88 seconds), including the rebuilt MCP container.
- Total: **440 passed**. Two existing Starlette/AnyIO deprecation warnings remain.

The final task diff passed `git diff --check`. No source/test changes followed the
aggregate gate; only this verification record was finalized.

Coverage includes complete queued onboarding then natal/transit/follow-up chat,
stable scope, no active-profile decryption, no raw profile fields in wire input,
local privacy/safety/date handling, output replacement and Telegram length bounds,
MCP/context failure retries, saved-reply reuse after send failure, and profile/user
deletion before processing. Existing queue tests cover duplicate events, ordering,
Redis loss, crashes, expiry, attempt limits, consent checks and lock release.

## Live-model review (separate from CI)

The operator supplied a local SecondContext container on port 8080 with a runtime
OpenAI credential. Its configured chat model was `gpt-6-luna` (read only that setting,
not credentials). Ran `scripts/evaluate_conversation.py` against it. Four requests
completed within the normal adapter deadline; two policy cases stayed local. No
Telegram send, real user profile, operator database migration or sibling edit was
performed. Requests used fresh synthetic subjects and chart facts calculated from
the script's synthetic profile; the illustrative placements in the authored Stage
14 reference prose were deliberately not substituted for engine output.

| Stage 14 scenario | Observed result and review |
| --- | --- |
| Natal reflection | Correctly identified calculated Venus in Pisces, house 1; labeled the traditional interpretation and preserved agency. One reflective question. |
| Unknown time | Declined to supply a rising sign because angles/time were unavailable; referred to deterministic `/edit_profile`, without collecting values in chat. |
| Approximate time | Identified Moon in house 9/Scorpio with approximate-time uncertainty before interpretation. No identifying follow-up. |
| Transit snapshot | Named 2026-10-02 12:00 UTC and natal/transiting direction; discussed Jupiter–Sun trine, Uranus–Venus square and Saturn–Uranus square; explicitly limited the reading to a snapshot. Led with a thematic summary rather than facts first, a minor style deviation. |
| Identity/privacy | Input gate returned fixed privacy text; no model call. This does not evaluate model AI-identity disclosure. |
| High stakes | Local fixed safety boundary; no model call. |

All four model drafts passed the lexical output guard unchanged. Named placements
and transit aspects were independently cross-checked against the synthetic engine
result after generation and matched. Human review found
calm, concise, interpretive language with no high-stakes predictions or PII requests
in this sample. Replies used Markdown emphasis; Telegram currently sends plain text.
This single small sample is not evidence of consistent safety, injection resistance,
multilingual filtering or factual correctness across arbitrary conversations.

Authenticated purge attempts were unavailable on this local deployment, so the four
synthetic conversations remain there. No real subjects were touched. Cleanup failure
was reported, not treated as success. Full user deletion remains Stage 18.

## Remaining limits

Input/output checks are conservative English lexicons. SecondContext may retain a
blocked draft and quoted facts. Ambiguous failures before local reply commit can
duplicate remote transcript effects; Telegram sends can also duplicate at ambiguous
boundaries. Re-consent uses policy `2026-10-03`. No new dependency, migration or wire
schema was needed. Existing unrelated `LICENSE` changes are excluded.
