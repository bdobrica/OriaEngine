# Private reading handoff — 2026-11-11

The participating user's Oria 0.2.2 review confirmed improved basic continuity but
exposed a handoff failure: after a horoscope, a compatibility request and private
birthday clarification produced a local reading, then a plain-English question
received another horoscope. Private birth answers/save receipts correctly stayed
out of history; the application lacked a safe reference to the new local reading.
No private transcript, birth value or account identifier is retained here.

## Correction

Oria application **0.2.3** adds an optional reading selector to the existing
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
answer quality. Publication, rollout and the limited live-model topic check passed;
the participating user’s private Telegram retest remains pending. The bounded whole-message follow-up grammar
is not CH4 Decisions classification or CH6 adaptive routing. This sequence is a
future classifier evaluation case; a classifier cannot reconstruct excluded input.

## Publication and live validation

Source `3f2633169c2624361a8ca49b446fb925929911d0` passed
[full and cross-service CI](https://github.com/bdobrica/OriaEngine/actions/runs/43063481062)
and [app publication](https://github.com/bdobrica/OriaEngine/actions/runs/43063481039).
Both linux/amd64 and linux/arm64 manifests were inspected; the pulled image’s
version/source labels matched. Gateway and worker now use:

`quay.io/bdobrica/oria-engine@sha256:ce186778827e7779b82f0717cddf5ab2b18bb63056a93323baff689d1c7579c2`

Only `oria-live-test` was maintained. Callers drained and owning Oria metadata
showed no unresolved history or ingress work before the update. Fresh owning-role
database dumps, a cold Qdrant archive and the private configuration were backed up;
archive structure was checked, but restore was not exercised. No migration was
applied: Oria remains 0013 and SecondContext 5 clean. MCP remains 0.2.1 and the
provider remains 0.2.2. The only configuration difference was the app image;
disclosure, flags, budget, model, credentials and encryption key were preserved.

The released adapter’s existing live history probe passed accepted replacement/local
recall, selective erasure and full purge. A separate fresh synthetic subject seeded
an older horoscope, then received current MCP-calculated synastry facts with the
compatibility follow-up cue, followed by an unrelated rainbow question and another
follow-up. All three generations were accepted. Limited content checks confirmed
relationship-related text without returning to a tomorrow forecast, then rainbow/light
content on both new-topic turns. This samples topic relevance; it does not establish
broad model quality or verify every interpretive claim.

The first operator topic probe failed before generation because its local-acceptance
constructor used the base record-reference DTO instead of the required history DTO.
Its fresh subject was purged. Correcting the temporary probe allowed the check to
pass; no application change or relaxed validation was needed. All probe subjects
were purged and private cleanup journals cleared. No real account payloads were
read and no Telegram messages were sent by these probes.

Services were healthy after startup. Gateway readiness and the existing, unchanged
Telegram webhook passed, with zero pending updates at inspection. The user has been
asked to start a fresh compatibility request and retest both its plain-English
follow-up and a later unrelated topic. Existing private exchanges are not backfilled.
SecondContext’s CH4 TODO also tracks this evaluation case; its existing local PLAN
remains unstaged. CH4–CH6 are not implemented or enabled by this correction.
