# Private reading handoff — 2026-11-11

The participating user's Oria 0.2.2 review confirmed improved basic continuity but
exposed a handoff failure: after a horoscope, a compatibility request and private
birthday clarification produced a local reading, then a plain-English question
received another horoscope. Private birth answers/save receipts correctly stayed
out of history; the application lacked a safe reference to the new local reading.
No private transcript, birth value or account identifier is retained here.

## Correction

Oria application candidate **0.2.3** adds an optional reading selector to the existing
encrypted, consent-scoped 24-hour progress envelope. It carries reading kind,
canonical references/revisions and the selected entity reference. It contains no
birth input, chart cache, transcript, receipt or copied model response. Ordinary
follow-ups select and recalculate that reading; the prepared message identifies
compatibility/event context alongside fresh typed facts. The original private
exchange remains excluded from provider history.

A new ordinary topic consumes the selector. Every source is checked for current
ownership/revision/review state; stale selection asks for a fresh choice. Expiry,
withdrawal and erasure use the existing progress lifecycle. Opt-out/unsaved
transient calculations create no selector. CRUD focus remains separate, preventing
a linked reading's own-birth dependency from broadening “forget that.” Multi-person
events preserve the original selected entity rather than selecting all participants.
Projection preflight permits ordinary focus but still skips pending private actions.

No public API/schema, provider runtime, migration, disclosure or dependency change.
Existing progress payloads remain readable; absent selectors serialize in the old
shape. Active selector payloads require 0.2.3-compatible code. Use capture controls
on that code for rollback; do not downgrade an active state reader to 0.2.2.
See [the behavior and limitations](../linked-readings.md#follow-ups-after-private-inputs).

## Verification

- Reproduced the old failure through real isolated SecondContext HTTP: the request
  after the local compatibility reading lacked both a reading cue and linked facts.
- The new regression passes through actual Oria workers and the real gateway with
  synthetic model replies: horoscope, private compatibility clarification, local
  reading, plain-English follow-up, then a new topic and its follow-up. It asserts
  current compatibility facts, source links, accepted receipt, and exclusion of the
  synthetic birthday/save receipt from actual model inputs.
- Focused linked-reading/history suite: **54 passed**. After tightening entity
  selection, all **19 linked-reading cases** passed, including a multi-participant
  event. **11 unit cases** cover supported follow-ups and rejection of new topics,
  dates, mixed requests and opt-out as selectors.
- Root `make verify` passed: Ruff, strict mypy (82 files), 14 release-selection
  checks, **611 unit**, **219 integration**, **391 contract**, **13 end-to-end**.
  Following final selector/serialization hardening, the full real-gateway suite
  passed again: **25 tests**. No private/production data was used in these lanes.
  Local commands use the existing `/tmp/oria-och2-uv.py` wrapper for installed tools.
- Final diff/format/type and local documentation-link checks precede publication.

Synthetic model responses prove the application handoff and lifecycle, not broad
answer quality. Publication, a scoped rollout, a live-model topic check and a private
Telegram retest remain to be recorded. The bounded whole-message follow-up grammar
is not CH4 Decisions classification or CH6 adaptive routing. This sequence is a
future classifier evaluation case; a classifier cannot reconstruct excluded input.
