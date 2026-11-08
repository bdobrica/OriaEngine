# Compatibility and event readings

Slice 5 connects the encrypted event/profile inputs to new, additive
[linked-chart tools and context facts](../contracts/astrology/linked-v1.md).
The implementation is local source work, not a published or live release.
Deploy matching application and Astrology MCP images before using these tools.
Optional memory still requires the separately verified
[SecondContext linked-context capability](linked-context.md).

## Conversation

Supported bounded English requests include:

- “I'd like you to rate my compatibility with my girlfriend. Her birthday is
  June 2nd, 1992.”
- “Rate my compatibility with Alice” after her birth event has been shared.
- “Interpret our wedding chart” after its date has been shared.
- “Interpret Alice and our wedding chart across the house themes.”
- “Read my business's chart” when its founding event is linked to that entity.
- “Don't remember this. Rate my compatibility with my girlfriend. Her birthday
  is June 2nd, 1992.” The supplied input is used for this calculation without
  adding canonical or interpretation memory. Separate chat/provider retention
  remains as disclosed; this is not a private-chat mode.

The application selects one other entity, its birth event and/or a non-birth
event under the owner lock. Names, aliases, participants and recent scoped focus
can identify records. Ambiguous people/occurrences need one focused selection;
a year can distinguish event occurrences. Unknown names never select another
account or silently fall back to a remembered partner. Dates on narratives alone
do not initiate calculations. Explicit own-profile changes retain `/edit_profile`.

Complete dates allow a birthday-only reading without time/place. These are labeled
noon-UTC samples, with no own houses/angles; they are not fabricated birth times.
Partial dates need the missing year/day for calculation. Dates outside 1800–2399
remain valid memories but cannot be calculated. Approximate dates/times retain
uncertainty. Useful discussion can continue without pretending to have missing facts.
When Oria asks for a missing partner/event date, a bare date answer resumes the
original reading using the existing encrypted, consent-scoped 24-hour clarification
state and original reference clock. It does not become a transit request. Opt-out
suppresses this additional temporary state too.

Explicit city/country labels resolve through the existing local gazetteer only
when exactly one place matches. A historical event clock uses its explicitly
supplied timezone, or its unambiguously resolved event place's historical timezone.
The current timezone preference is not a historical birth timezone. Without a safe
clock conversion, positions use the labeled date sample; no DST occurrence is
silently selected. More detailed date/place clarification still uses the existing
bounded event controls; this is not general multilingual extraction.

The same tropical convention applies to human/pet births, founding or possessions'
events without requiring their registration or consent. A non-birth event chart
does not modify anyone's natal profile.
For a non-person entity, a selected founding/purchase/adoption event can supply
the other chart in a requested compatibility reading. The facts explicitly label
its convention as an event rather than inventing a human birth.

## Facts, themes and ratings

Every linked reading recalculates selected charts from current authorized inputs.
Self/other/event can supply three pair comparisons. Current typed facts include
planetary positions, static major cross-aspects and directional house overlays
where receiving houses exist. No event cause, private intention, empirical
correlation or future outcome is established by those calculations.

All twelve [traditional house themes](conversation-memory-plan.md#twelve-house-interpretation-reference)
are available in prompting and bounded retrieval: identity; values; communication;
home; creativity; routines; partnerships; shared resources; philosophy; career;
networks; unconscious/endings. Explicit numbered house requests, topic words and
current measured overlays select themes. No time is needed for thematic discussion.
Oria selects relevant themes rather than reciting twelve houses on every turn.
Tags never substitute for calculated placements.

Requested ratings use the explicit symbolic `oria-reflection-rating-1` convention
described in the contract. Oria explains a few supplied contacts behind the rating.
The scale is interpretive, not a probability or scientific compatibility measure.
It is independent of SecondContext's salience/relevance score. Routine general
disclosures remain in consent/help/privacy; readings mention only a relevant gap.

## Memory, corrections and availability

There is no new persistent calculated-feature cache or migration. The current
facts packet pins the calculation method and source revisions; each new reading
recomputes. Existing encrypted projection work can retain a qualitative reading
summary, omitting raw inputs and numeric chart values, and referencing own birth,
the selected entity, its birth and event revisions. Existing invalidation/erasure
retires these dependent readings on profile/event/entity correction or removal.
Old readings are recollections, never replacement chart facts.

When linked memory is enabled, a remote generated reading includes the exact
acknowledged source references as `knowledge_refs`, even if retrieval found no
prior interpretation. SecondContext validates and links the session before a
draft, preserving selective erasure of the retained facts/session. If source
projection delivery or erasure is pending, or more than twenty source links would
exceed the response contract's bound, Oria gives a local calculated reading
and queues the minimal interpretation after the same local transaction. It does
not force an uncommitted remote mutation or send unlinked current facts. After
delivery, normal generated readings and linked recall resume. Model-provider
unavailability can also fall back to this local reading. MCP failure yields the
existing generic retry path, without invented or partially accepted results.

With optional linked memory disabled, ordinary v1 generation/retention remains
unchanged; selective remote session erasure is not promised. The current expanded
consent `2026-11-08.5` already discloses calculated facts and filtered interpretations;
this slice adds no raw-input forwarding or new storage category. Coordinated
publication, live-provider review and rollout remain slice 6.

[Verification evidence](evidence/linked-readings.md) records the aggregate gate,
synthetic reading cases and real HTTP MCP checks.
