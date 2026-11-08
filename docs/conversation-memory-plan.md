# Natural time, entities and life-event memory

Status: policy, bounded natural time, local encrypted memory and optional
[SecondContext linked context](linked-context.md) are implemented. Linked calculated
readings and coordinated release remain. [ADR 0002](adr/0002-private-life-events-and-context-projections.md)
and the [versioned contracts](../contracts/knowledge/v1.md) preserve ownership.
No deployment is implied. Track delivery
in [TODO](../TODO.md#current-priority--natural-time-and-life-event-memory).

## Conversation policy

Oria is an ongoing conversational companion with an astrology perspective for
consenting adults. Users are responsible for what they choose to share, including
PII about themselves and entities in their lives. Entities include people, pets,
businesses, non-profits and possessions such as a house, car or phone. They do not
need accounts or separate acceptance of Oria's policy. Personal information, a
third-person mention or a sensitive topic is not by itself grounds for refusal.

After the versioned disclosure and adult agreement, Oria should converse and
provide useful insights on any topic. Ask relevant questions, accept partial
information and remember meaningful disclosed context naturally. Do not require
a separate save command or consent ceremony for each event within the accepted
data use. A transient hypothetical, quoted example or question about a date is
not automatically a fact about the user. Respect “don't remember this.”

Oria remains responsible for secure storage, isolation between accounts, accurate
representation of what is known, and usable retrieval, correction and deletion.
The user's responsibility for sharing does not transfer those duties to the user.
General disclosures belong in consent/help/privacy, without recurring warnings in
ordinary chat. Explain only specific missing information that matters to an answer.

Intervene when the requested response could encourage or enable harmful or
destructive behavior toward the user or another entity. Assess the actual request
and proposed answer rather than banning words or entire subjects. Talking about
health, money, divorce, grief, a business closing or replacing a car is ordinary
conversation. Threats, self-harm encouragement, abuse, sabotage or instructions to
act dangerously call for a brief, specific boundary and useful safer continuation.
Do not invent distress or harmful intent from the topic alone.

Open discussion does not authorize private-account access, disclosure of another
user's data, fabricated facts or model-granted tool permissions. Interpretations,
including requested compatibility ratings, remain interpretations. A remembered
story or an astrological association cannot establish private intentions, medical
facts, causation or a guaranteed future outcome.

## Natural dates and time

Relative language is a first-class input, not an error that normally requires an
ISO date. Support absolute, relative, mixed and event-anchored expressions in
conversation, including several dates and entities in one message. Preserve their
roles: an event date, a birth input, an anniversary, a calculation target and a
saved-profile correction are different things.

| Example | Intended resolution |
| --- | --- |
| “in two hours” | An elapsed duration from persisted message arrival, unchanged by retries |
| “today”, “tomorrow” | A local calendar day in the user's selected current timezone |
| “this day last year” | The corresponding local calendar date in the previous year |
| “exactly nine months ago” | A calendar-month offset, not nine times thirty days |
| “May 1st, 2020” | A date-only event unless a time is supplied |
| “May 1st, last year” | Month/day combined with the year relative to message arrival |
| “a week before my birthday” | Seven calendar days before the relevant birthday occurrence; clarify the year only if context does not select it |
| “we married this day last year at 3pm” | A wedding event, its participants and local date/time, not an automatic transit request |
| “my girlfriend was born …” | A birth event for an entity in this user's scope, not an edit to the user's own profile |

Use the message's persisted aware UTC arrival timestamp as the reference clock.
Use an explicitly supplied event timezone for that event, or the user's explicitly
selected current timezone for local relative language. Do not infer current or
historical event timezone from birthplace, an entity's name or a model guess.
When timezone affects the answer and is missing, ask one focused question.
An absolute date can still be stored without knowing its timezone or time.

Represent instants, date-only values, partial dates, intervals and recurring
anniversaries distinctly. Never turn an unknown event time into noon or midnight
in canonical records. Separate a historical birth/wedding from its annual recurrence.
“My birthday” and “the day I was born” need not refer to the same year. Preserve
approximate dates/times and uncertainty without demanding precision the user lacks.

Calendar arithmetic needs explicit tested rules: local day/week operations versus
elapsed UTC hours, month-end clamping, February 29 anniversaries, and invalid or
repeated local clock times at daylight-saving changes. Use the existing month-end
clamping convention for offsets; ask about February 29 observance when it matters,
and clarify nonexistent/repeated clock times rather than silently selecting one.
Store the original expression encrypted, the resolved value/precision, reference
clock, timezone source, anchor event/version and resolution-rule version. Later
retrieval must not re-evaluate “last year” against today's clock. Anchor corrections
invalidate dependent resolutions; do not silently rewrite an independently stated
historical fact to follow a changed anniversary.

Extraction may propose structured candidates; application validation resolves dates,
ownership and permitted operations. Model output alone never authorizes a write,
calculation, account selection or timezone change. Retain short-lived, encrypted,
owner-scoped clarification state so “at 3pm” can finish the pending event. Do not
force users to repeat the whole story or replace their wording with an ISO date.

Preserve the published v1 transit snapshot conventions until an explicit compatible
route/contract transition exists: legacy ISO dates use noon UTC, and bare “today”
uses message arrival. New event records keep date-only precision; a calculation
sampling convention is separate, labeled and never represented as a known event
time. Support date ranges for conversation; only claim a period reading once the
calculation service actually supplies interval coverage. Storage need not impose
the engine's 1800–2399 calculation range on otherwise valid historical events.

## Canonical user knowledge in Oria

Extend the user's private profile with related records, preserving the existing
strict natal-profile schema and its explicit edit workflow. Logical
records below describe the design; [private memory](private-memory.md) identifies the implemented local subset and limits. [Linked context](linked-context.md) adds
optional interpretation projections and durable work; linked calculated features remain planned.
An own-birth event should reference the canonical natal-profile revision rather
than create a second, independently editable source for the user's birth inputs.
Conversational corrections to other events must not silently mutate that profile.

| Record | Minimum information |
| --- | --- |
| Entity | Owner UUID, stable entity UUID, kind, user-supplied label/aliases, relationship to the user, revision and provenance |
| Life event | Owner UUID, stable event UUID, type/description, participating entity references and roles, temporal value/precision, optional place/timezone, source and revision |
| Relationship | Owner-scoped entity links, user-stated relationship and optional validity period; distinguish current and former relationships |
| Derived reading | Referenced event/entity revisions, validated calculation result/version, interpretive summary and its provenance |
| Projection work | Owner, record UUID/revision, operation and retry state; no PII in broker payloads |

Cover the user's birth, marriage, house purchase, pet adoption, job change and
business foundation, as well as parents' divorce or a partner's birth. Permit
user-described event types without inventing a mandatory taxonomy for all life.
An entity can have many events, an event many participants, and an event need not
have a known date. A business founding or pet birth is not a human natal profile;
any applicable chart convention must be explicit in calculation provenance.

Store sensitive content encrypted in Oria PostgreSQL, like existing profiles.
Keep indexing metadata minimal, queries owner-scoped, and relationships constrained
to records with the same owner. The same named person mentioned by two users has
two independent scoped records; never merge them across accounts. Do not link a
partner's supplied birthday to that partner's actual Oria account. Resolve “my
wife”, “my girlfriend”, pronouns and aliases from this user's context; ask when
ambiguous rather than merging people speculatively. Corrections can add evidence,
change a value or split a mistaken merge without losing provenance.
Repeated mentions should retrieve/update the same event when its identity is
clear; ask about genuinely ambiguous occurrences instead of duplicating or merging
distinct weddings, jobs or purchases. Ownership always comes from authenticated
application scope, never a model-supplied owner field.

Natural chat should support:

- learning a clearly disclosed meaningful event and acknowledging it briefly after
  the application commits it;
- “what do you remember about our wedding?” and profile inspection of records;
- “it was May 2nd, not May 1st” with revisioned updates and invalidation of readings;
- “forget my ex's birthday” or “forget that business”, with clarification if the
  target or cascade is unclear, followed by deletion of affected dependent data;
- “don't remember this” without a persistent event or semantic-memory write, and
  accurate explanation of any separate conversation/provider retention limits.

Do not claim saved/updated/deleted status before the corresponding application
operation succeeds. Deduplicate mutation work by inbound event and logical operation;
serialize against edits, withdrawal and account deletion using the owner lock.
Current consent gates learning and interpretation; inspection and deletion retain
their existing availability without current consent. Do not bulk-convert old
transcripts or sketches into profile facts. Automatic learning concerns newly
disclosed context under the accepted data use, with correction and opt-out controls.

## Salience and linked interpretation in SecondContext

Oria owns canonical user-supplied entities/events. SecondContext owns its scoped
context and salience projections. Extend its authenticated versioned HTTP contract
in the owning repository; never write its database or Qdrant from Oria. The legacy
v1 subset admits fixed memory phrases and subject-wide purge; the optional
[linked-context lane](linked-context.md) now adds the projection lifecycle.

Project the minimum useful labels, stable entity/event references and revisions,
user-stated significance, topics and derived interpretation summaries. Keep raw
birth dates/times/places and calculation inputs in Oria's calculation path rather
than embedding them as general memories. Handle conversational birth inputs before
context forwarding, using references and locally calculated facts; allowing a
birthday in chat must not simply forward raw birth details through the old filter.
Specify exactly which non-birth event attributes can cross the new context boundary
and appear in transcripts in the new disclosure and versioned schema. User labels,
salience and interpretive summaries can themselves be sensitive; scope and delete
them accordingly. No arbitrary metadata bag or raw-profile memory shortcut.

Separate these types of knowledge:

- **User statements:** “Our wedding is especially important to me,” with source.
- **Derived salience:** changing relevance inferred from explicit importance,
  recurrence, recency and current conversation; version the scoring rules and let
  user corrections override an inference. Frequent mention alone is not importance.
- **Calculated features:** typed outputs with input revisions, engine/method and
  availability, verified by Oria before use.
- **Astrological interpretations:** tentative links between supplied calculated
  features and themes, attributed to a reading rather than promoted into facts.

Retrieve relevant event/entity-linked context on every turn that refers to those
records or their themes, including pronouns and follow-ups. Use bounded retrieval
and application rehydration of current authorized records, rather than inserting
the entire life history into every prompt. Reject deleted, wrong-owner or stale
references. Recalculate invalidated features before making new chart claims.
When SecondContext is unavailable, use authorized canonical facts where possible
and say only which remembered interpretation could not be retrieved. Do not invent
missing memories or silently resurrect an older projection.

Use durable Oria-side projection work and idempotent, revision-aware upsert/delete
operations. Define acknowledgements, ordering and reconciliation through the wire
contract before enabling ingestion. Delayed writes must not overwrite corrections
or recreate deleted records. A local deletion fence suppresses stale retrieval
immediately while remote erasure retries. “Forgotten” requires the promised remote
cleanup to complete, not just hiding one search result.

Single-record correction/deletion must cover dependent summaries, vectors, graph
links and retained transcript/draft references where the product promises erasure.
Existing subject-wide purge cannot be presented as selective deletion. Require
SecondContext-owned support and test its actual coverage before promising granular
remote erasure. Distinguish changing a canonical date from rewriting chat history;
disclose any retained copies honestly. Full account deletion covers all new Oria
records, pending projection work, SecondContext content and active indexes under
the existing durable purge workflow. Preserve documented backup/provider limits.

## Twelve-house interpretation reference

These are traditional topic associations for retrieval and interpretation, not
calculated placements or proof that an event had an astrological cause. An event
can relate to several themes. A wedding might involve partnership, home and shared
resources; it is not automatically a measured placement in houses 7, 4 and 8.

| House | Domain | Traditional topics |
| --- | --- | --- |
| 1 / Ascendant | Identity and self | Self-image, appearance, first impressions, vitality, personal style and immediate reactions |
| 2 | Finances and values | Earnings, possessions, personal resources, security, self-worth and material comfort |
| 3 | Communication and community | Thought, learning, siblings, neighbors, daily communication, local travel and early education |
| 4 / Imum Coeli | Home and roots | Family, parents, childhood, domestic foundations, privacy and emotional security |
| 5 | Creativity and pleasure | Creative expression, romance, hobbies, children, play, joy and risk-taking |
| 6 | Health and daily routines | Physical well-being, habits, diet/exercise, daily work, organization, service and pets |
| 7 / Descendant | Partnerships and alliances | Marriage, committed relationships, cooperation, business partnerships, contracts and open conflict |
| 8 | Transformation and shared resources | Birth/death/rebirth symbolism, intimacy, inheritance, investments, joint finances, taxes and deep emotional bonds |
| 9 | Philosophy and expansion | Higher education, long-distance travel, beliefs, religion, publishing, law and the pursuit of meaning |
| 10 / Midheaven | Career and public status | Ambition, vocation, authority, reputation, achievements, legacy and long-term goals |
| 11 | Networks and aspirations | Friends, groups, networking, collaboration, humanitarian causes and collective hopes |
| 12 | The unconscious and endings | Dreams, subconscious patterns, isolation, secrets, mental-health themes, spirituality, karma symbolism and closing cycles |

House-topic tags can support retrieval without a birth time. Actual natal houses,
angles, event charts, overlays and synastry require the appropriate inputs and
validated calculation tools. Unknown/approximate times retain their limitations.
Do not presume an astrological correlation between birth dates and a wedding:
calculate supported features first, then offer an interpretation if relevant.
Do not turn health/death/mental-health symbolism into diagnosis or predictions.

## Delivery sequence and acceptance

Implement each slice with focused tests, then the practical repository gate.
Keep legacy schemas and consumers working; regenerate schemas from their sources.
No change to live images or unrelated host containers is part of this plan.

| Slice | Deliverable | Acceptance before enabling |
| --- | --- | --- |
| 1. Policy and contracts | Implemented Oria policy/guard foundation, candidate typed temporal/event/entity and projection contracts, ADR 0002 and versioned voluntary-chat disclosure | Synthetic benign/harmful cases and consumer contracts checked; no event storage enabled; proposed lifecycle still needs acceptance/implementation by SecondContext before slice 4 ingestion |
| 2. Natural-time routing | Implemented bounded English/Gregorian parsing, typed date roles/precision and encrypted 24-hour clarification; local own-birth, same-message and supplied anchors | Design examples, multiple dates, leap days, DST, retries and missing timezone checked; no partner birthday routed to own-profile edit or transit by default; historical event recall awaits slices 3–4; see [current behavior](current-time.md) |
| 3. Private profile memory | Implemented encrypted entities/events, provenance and bounded conversational learning/CRUD; see [private memory](private-memory.md) | Restart, owner isolation, aliases, correction, deduplication, withdrawal/deletion races and “don't remember” verified; no false save acknowledgements |
| 4. Context continuity | Implemented optional [linked context](linked-context.md): revisioned projections, salience, interpretations, bounded linked retrieval and encrypted reconciliation | Owning-service HTTP tests cover revision/idempotency fences, selective linked-session erasure and full purge; rollout requires migrations, compatible release, explicit switch and disclosure 2026-11-08.4 |
| 5. Linked astrology | Birthday-only support, synastry/event calculations and house-topic retrieval, with versioned facts | Synthetic birth/partner/wedding reading uses actual supplied calculations; no invented times, houses, correlations or precision; corrections invalidate dependent readings |
| 6. Release | Updated consent copy/version, review fixtures, full verification and published images | Existing users accept expanded data use before new storage starts; multi-turn review and end-to-end lifecycle pass; deploy only identified Oria services after publication |

Runtime policy changes must be capability-aware: allowing an input does not permit
claiming unsupported storage or calculation. Do not enable remote event ingestion
ahead of its deletion contract. General conversation and honest partial readings
should continue while later slices remain unavailable.

Start with the existing English conversation surface, using a compositional
temporal representation rather than hardcoding these example sentences. Declare
supported locale/calendar conventions; ambiguous numeric date formats need context
or clarification. Other-language support needs its own parser/review coverage,
rather than implying that all natural-language expressions are already understood.

Use synthetic regression conversations covering every user example, all entity
types, independent users with the same entity labels, repeated/corrected dates,
multiple anniversaries, linked multi-house themes, benign sensitive discussion and
actual harmful intent. Evaluate recall usefulness and false refusals alongside
calculation accuracy, isolation and erasure. Run focused unit/contract/integration
tests, migration/schema compatibility checks and `make verify`; live-provider and
private Telegram checks are separate explicit evidence, not inferred from health.
