# Private events and entities

Migration `0011` implements the local canonical-memory slice of the
[conversation plan](conversation-memory-plan.md), under [ADR 0002](adr/0002-private-life-events-and-context-projections.md).
It does not enable SecondContext knowledge endpoints, semantic projections, salience,
synastry or event-chart calculations. Apply migrations and use consent version
`2026-11-08.3` consistently before collecting this expanded data. Custom policy
versions must also change. No live deployment is implied by the source change.

## Conversation

With a current consent and active chart profile, bounded English assertions can
save meaningful context without a separate save command:

- “We married May 1st, 2020.”
- “My girlfriend Alice was born June 2nd, 1992.”
- “I bought my house in May 2020.”
- “I got the cat exactly nine months ago.”
- “I changed my job yesterday.”
- “I founded my business.”
- “My parents got divorced this day last year.”
- “Remember that I won a prize in 2021.”

Entities include people, pets, organizations and possessions. Explicit names and
relationship labels become local aliases. “My girlfriend is Alice” followed by
“Her birthday is …” can use a single recent entity. Names do not resolve another
Oria account. An ambiguous person or occurrence asks for a numbered selection;
“another person” / “another event” creates a distinct record. A repeated clear
mention reuses a record. A conflicting date asks whether it corrects an occurrence
or describes another one. A new name for an occupied relationship does not silently
merge people. Former relationships can be stated with “correct Alice relationship
to ex-girlfriend”; a name correction preserves the old name as an alias.

`/memories` (also `/memory`) lists local records; a query can follow the command.
“What do you remember about our wedding?” retrieves current canonical data locally.
“It was May 2nd, not May 1st” corrects a single focused event. A month/day correction
retains the known calendar-date year when valid; it does not invent a time.
A replacement temporal value retains the supplied precision; include a time when
replacing a dated clock value. “Correct our wedding place to …” changes only the
place label, without inferring coordinates or a timezone. Explicit “correct our
wedding to …” selects a record by label. Missing correction dates and ambiguous
records use short-lived encrypted progress, so an answer can finish the operation.
Your own birth remains the strict natal profile: its event is a virtual reference
to that profile UUID/revision, with no duplicate birth fields. `/edit_profile`
continues to require explicit confirmation for corrections.

“Forget my ex-girlfriend's birthday” removes the selected event. “Forget that
business” selects the entity and asks before removing linked events when the
cascade needs clarification. “Forget my birthday” removes the canonical birth
profile, unfinished profile copies and derived chart; referenced local events are
included in the cascade. Inspection and removal remain available after withdrawal,
including through queued privacy requests. Deleted accounts cannot use these controls.

“Don't remember this” prevents the additional canonical/progress writes. It does
not establish a private-chat mode or erase separate queue/transcript/provider copies.
Questions, examples, hypotheticals and recognized negations are not learned as facts.
The extractor is a bounded grammar, not general natural-language understanding:
unsupported forms continue through existing conversation without a save receipt.
It does not import old transcripts, authored sketches or model-generated claims.

Memory controls run locally. A separate explicit reading request can continue after
a save; only the prepared request goes to the existing provider. The local save
receipt is composed by the application. No arbitrary canonical payload, record ID,
raw birth input or new memory projection is added to that API. Existing non-birth
resolved date context remains governed by the [time reference](current-time.md).

## Storage and authority

`KnowledgeRepository` uses the caller's transaction and authenticated owner UUID.
The candidate [canonical v1 DTOs](../contracts/knowledge/v1.md) validate local records;
they still do not authorize remote routes. No model extraction or write tool is enabled.

| Table | Content |
| --- | --- |
| `knowledge_records` | Owner/record UUID, kind, revision, review/deletion metadata, AES-GCM ciphertext and key version |
| `knowledge_links` | Same-owner participant/anchor dependencies, enforced by composite foreign keys |
| `knowledge_changes` | Source operation UUID, record revision and timestamp; no old payload copies |
| `knowledge_operations` | Payload-free, owner-scoped inbound mutation receipts |
| `knowledge_dialogues` | Encrypted focus/record selection/correction, consent binding and expiry |

Labels, aliases, relationships, descriptions, place and temporal evidence remain
inside ciphertext. AAD binds owner, UUID, kind, revision and encryption-key version;
copying ciphertext between users, kinds or revisions fails. There is no plaintext
name/date search index. Queries decrypt at most 1,000 live owner records. The runtime
keeps the existing encryption key configuration and does not add dependencies.

Temporal evidence preserves source expression, ingress clock, precision, timezone
source, anchor UUID/revision and resolver version. Date-only, partial and unknown
values retain their precision. A local clock with unknown timezone is not UTC.
Saved dates are not re-evaluated on lookup. Approximate dates remain available for
inspection but are not promoted into exact calculation anchors. Saved event references can resolve later
relative expressions, and ambiguous occurrences ask instead of choosing arbitrarily.
Corrections invalidate dependent resolutions for review without rewriting independent
historical facts. There are no linked calculated readings to regenerate yet.

Mutations share the user lock with consent, profile edits and deletion. Current
consent permits learning/correction; lookup and erasure require an active owner,
without current consent. An inbound logical operation has a stable, owner-scoped
UUID across clarification and retries. Mutation plus reply commit atomically in the
worker. An ambiguous multi-record turn rolls back all candidate changes before
asking its question. Provider failure rolls back a save awaiting a combined reply.
Telegram delivery retries use the committed reply without repeating mutations.

Focus/selection and date questions expire 24 hours from their original reference;
answers do not extend that window. Withdrawal, explicit profile editing and erasure
clear suspended state. Recovery scans erase expired ciphertext. Stale selections
are revalidated by owner, UUID and revision; a changed deletion cascade requires a
new acknowledgement. Record UUIDs cannot be resurrected after erasure. A new,
intentional disclosure uses a new UUID; replay of an old mutation cannot recreate it.

## Erasure scope

Local selective erasure removes payloads, dependent local records, provenance links
and pending progress, retaining only minimal tombstones and operation receipts to
fence replays. Correction replaces ciphertext and retains provenance identifiers,
not obsolete private payloads. It does not rewrite a prior human conversation.

Earlier independent chat, provider drafts, Telegram history, backups and retired
copies have separate lifecycles. A local removal receipt says so; it never claims
remote selective erasure. SecondContext knowledge ingestion stays disabled until
slice 4's owning-service lifecycle is accepted, implemented and tested. Existing
[account deletion](deletion.md) erases every new local table and still waits for
validated full-subject remote purge before completion.

See [verification evidence](evidence/private-profile-memory.md). Run focused memory
unit/integration tests, migration compatibility checks, then `make verify`. Tests
use synthetic records and isolated Oria projects; never use the MVP for this gate.
