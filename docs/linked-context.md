# Linked salience and interpretation memory

Slice 4 adds an optional, scoped SecondContext projection lane under
[ADR 0002](adr/0002-private-life-events-and-context-projections.md). Oria remains
owner of [encrypted canonical events/entities](private-memory.md). SecondContext
owns projected summaries, salience ranking, retrieval and linked-history erasure.
Neither component reads the other's database or internal implementation types.

## Enablement

The verified owning-service source is SecondContext commit `287e201` (not yet
published by this task). Apply Oria migration `0012` and SecondContext migration `000004`, deploy the
compatible `linked-context-1` SecondContext implementation, and configure:

```dotenv
ORIA_POLICY_VERSION=2026-11-08.5
SECOND_CONTEXT_KNOWLEDGE_ENABLED=true
SECOND_CONTEXT_SUBJECT_NAMESPACE=oria
```

Use the existing private scoped service credential, never a model-selected subject.
The feature defaults off for compatibility with published images. Do not enable it
against the existing MVP images: source verification does not publish or deploy a
release. Both ingress and workers need the new disclosure version; custom policy
versions must also change. Users re-consent before new projection collection.
Existing canonical records are projected on an eligible active turn after consent;
old transcripts are never bulk-imported.

Before any outbox delivery Oria validates the authenticated, exact-subject
`/v1/knowledge/capabilities` result: contract 1, implementation `linked-context-1`,
Postgres index and `linked_sessions` history coverage. Health, unknown endpoints or
partial acknowledgements cannot enable ingestion. See the
[versioned wire contract](../contracts/knowledge/v1.md) and owning-service contract.

## Data and meaning

| Projection | Contents |
| --- | --- |
| Canonical entity summary | Checked label, entity type and relationship; self UUID/revision |
| Canonical event summary | Bounded recognized event type, or generic life event; self UUID/revision |
| Participant link | Event type, checked participant labels and exact canonical references |
| Significance statement | A bounded explicit high/low importance assertion linked to known records |
| Prior interpretation | A guarded, filtered, date-free prior reply, or a minimal qualitative linked-reading summary, with flattened canonical source references |

Aliases, source messages, event descriptions, temporal expressions, dates, clocks,
places, raw birth profiles, coordinates and provider IDs are not projected. Labels
containing recognized dates/birth language/secrets become generic entity types.
Ordinary interpretations containing digits, recognized birth/date language or secrets
are not remembered; linked calculated readings can instead retain a minimal application-owned
qualitative summary of the supplied contacts with canonical dependencies. No raw inputs
or chart numbers enter that summary; mentions of known birth places are also withheld. This conservative
filter can omit useful readings. It does not establish general semantic PII detection.
All labels and narratives remain untrusted data, even after application validation.

Traditional house themes 1–12 support retrieval. Wedding themes can include home,
partnership and shared resources; these tags are not calculated houses, measured
placements, or evidence of an astrological correlation. [Slice 5 linked readings](linked-readings.md)
add separate current calculation facts, requested symbolic ratings and measured overlays.
Their source revisions also link generation sessions; pending source delivery/erasure
uses a local reading rather than sending unlinked facts.

SecondContext's `linked-salience-1` heuristic combines importance (0.60), recency
(0.15, exponential 30-day scale), exact link relevance (0.20) and topic overlap
(0.05). Default inferred importance is neutral 0.5. Supported explicit significance
phrases create attributed high/low statements; later statements supersede earlier
ones for overlapping sources. The latest explicit statement overrides inferred
importance when ranking related projections. Mention frequency is not importance.
Scores are relevance heuristics, not probabilities or relationship ratings.

## Conversation and retrieval

Ordinary discussion can refer to known labels/aliases, participants, themes or
recent pronoun focus. After a relevant guarded reading, an eligible interpretation
is queued automatically without a new permission prompt. “What do you remember
about Alice?” and `/memory Alice` can include prior interpretations alongside the
current canonical records. No model output can write canonical data or grant tools.
“Don't remember this” suppresses this turn's additional projections and interpretation
writes; the separate disclosed conversation/provider lifecycle still applies.

Queries request at most six items by current record references and/or house themes.
Oria requires an exact match to its encrypted desired projection, checks every
canonical source under the requesting owner's lock, and rejects deleted, altered,
wrong-owner, pending and stale items. Only validated references go on the additive
`knowledge_refs` response field. SecondContext rechecks those references/sources
under its own subject lock before generation and links the session before any draft
is generated. Recalled statements/interpretations enter as untrusted context;
current calculated facts still come only from the typed astrology path.

No full life history is inserted in prompts. Recent focus expires under the existing
24-hour policy. The extractor and significance phrases are bounded English rules,
not a general semantic understanding of every possible assertion. When retrieval
fails, ordinary supported conversation continues without pretending to recall an
unavailable reading. New or corrected context becomes available after delivery;
readings do not synchronously force an uncommitted remote write.

## Durability, corrections and erasure

`context_projection_work` stores one encrypted desired payload per owner/record,
its kind/revision, immutable operation UUID for that delivery, acknowledgement state,
and content-free retry bookkeeping. AES-GCM AAD binds owner, record, kind and
revision. There is no plaintext local label index or historical payload archive.
Up to 2,000 projection/tombstone rows per owner bound this demonstration lane.
At most 1,000 canonical records retain the existing local limit.

Learning and outbox staging share the canonical transaction. Remote mutation starts
only after that transaction commits. Recovery runs directly from Postgres alongside
existing worker recovery, without depending on Redis. It handles up to four owners
and four operations per owner per scan; delete work has priority. Exact typed receipts
are required. Ambiguous writes retry the same operation/body, and failures back off
up to an hour. No request payload or response body is stored in retry diagnostics.

Canonical corrections replace desired summaries at the new revision and retire
linked interpretations and significance that depended on old revisions. Links are
rebuilt with fresh derived UUIDs; projection work never invents a canonical revision.
Own-birth projections use the real profile UUID/revision. Active reading memories
also depend on that profile revision even when retrieval selected only an event or
entity, so a birth-profile edit invalidates their natal interpretation. Oria suppresses stale
retrieval immediately. A corrected event whose date needs review cannot ground an
interpretation. A later actual canonical correction can be projected normally.

Selective deletion wipes queued ciphertext and commits terminal deletion work with
the local erasure. The initial receipt says remote cleanup is queued; it does not
claim complete remote forgetting. `/memories` reports pending cleanup. All linked
recall is suppressed while any selective erase is pending. Erasure retries even
if consent is withdrawn or the feature is disabled; upserts remain consent/feature
gated. Account deletion erases local work and uses the full-subject purge instead.

SecondContext persists a terminal record fence and payload-free operation reservation
before cleanup. Queries and generation exclude fenced/stale dependencies, even when
cleanup fails. Retry removes dependent summaries, Postgres indexes, link records and
**entire linked response sessions**, including their user messages, assistant drafts
and retained context packets. This deliberately broad history coverage can remove
unrelated turns within the same linked session. Completion requires the owning
service's exact erasure receipt; incomplete cleanup returns failure. The projection
lane does not write vectors, legacy cognitive models or graphs, so it creates no
untracked derivative stores. Legacy fixed-phrase preference memory stays separate.

Independent conversations not linked through this protocol, backups, retired indexes,
Telegram history and external-provider retention have separate lifecycles. Selective
removal does not promise to rewrite every past human mention. Full-subject purge
also removes projection content, operations, links and record fences while retaining
the existing minimal subject fence against delayed requests. No API can resurrect a
deleted UUID; a genuinely new intentional record gets a new UUID.

See [verification evidence](evidence/linked-context.md). Published images and live
provider/Telegram validation are separate release work.
