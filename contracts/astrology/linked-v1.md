# Linked astrology v1

This additive contract introduces `calculate_event_chart(request)` and
`calculate_synastry(request)` on the existing private MCP transport. It leaves
[`calculate_natal_chart` v1](v1.json) and [transits v1](transits-v1.json)
unchanged, including unknown-time unavailability. The generated
[linked schemas](linked-v1.json) define closed request/result DTOs and the Oria
context-facts packet. Regenerate through `scripts/generate_astrology_schema.py`.

## Inputs and calculation provenance

Each request carries contract version 1 and an ephemeral `calculation_id` UUID.
The result must echo that exact token. Tokens are not owner, person or record IDs.
MCP receives no identities, labels, account selectors, saved record references or
place names. It remains stateless, without storage, LLM, geocoder or network calls.
Only consent-scoped application code selects inputs and tools.

Each chart has either an aware, zero-offset UTC timestamp with accuracy `exact`
or `approximate`, or a `calendar_date` with accuracy `unknown`. Date sampling
can carry `date_approximate`; it cannot accompany a known timestamp. Coordinate
pairs are optional and bounded; Gregorian years 1800–2399 are supported.
The declared known/unknown state cannot supply both a date and an instant.

`oria-linked-1` reuses the pinned `oria-natal-1` astronomy: ten apparent geocentric
tropical ecliptic longitudes, Swiss Ephemeris 2.10.03 / binding 2.10.3.2,
Moshier and its existing UTC/TT/UT1 conventions. Exact/approximate charts with
coordinates reuse the existing Placidus calculation. Unsupported houses have no
replacement system. A known timestamp without coordinates can supply positions,
but no houses/angles.

For `unknown` time, `calendar-date-at-12-utc-1` computes a **conventional sample
at 12:00 UTC on the supplied calendar date**. This is not a birth/event instant,
not necessarily local noon and not an interval or uncertainty envelope over the
possible local day. No hidden timezone or default coordinates are inferred.
All sampled positions, signs, cross-aspects and projected overlays can change
with actual time/timezone, especially the Moon and cusp-adjacent values. A sampled
chart has `precision=date_sample`, a `date_only_sample` reason and no own houses,
planet houses or angles. Approximate dates additionally carry `approximate_date`.
This explicit partial-reading convention does not reinterpret natal v1.

`ChartFacts` contains ten distinct planets, precision, cusps/angles when supported,
and closed reasons. Results omit timestamps, calendar dates, coordinates and all
raw calculation inputs. Metadata pins astronomy, sampling and comparison versions.
The engine's decimal values are numerical results, not a claim to physical accuracy.

## Synastry and event comparisons

The two charts are consistently A and B, even for a same-body comparison.
`static-longitude-major-6deg-1` visits all 100 cross-chart body pairs. It returns
conjunction, sextile, square, trine and opposition within the existing inclusive
six-degree orb, shortest unsigned separation and unrounded orb. There is no
applying/separating velocity or time-to-exact for charts at different instants.

An overlay `a_in_b` places A's longitudes inside B's calculated cusp intervals;
`b_in_a` reverses that direction. Intervals include their starting cusp. Each
receiving chart with houses yields ten overlays. A sampled receiving chart never
has houses. Sampled longitudes may be overlaid on a known receiving chart, but
every such overlay remains `date_sample`. Either approximate known time makes
an otherwise non-sampled overlay approximate.

Consumers validate token/precision correspondence, ten-body/sign consistency,
complete cusp geometry, static cross-aspect geometry and overlay direction,
coverage, house assignment and precision. Invalid/partial/mismatched results fail
closed with a payload-free `AstrologyUnavailable`; cancellation propagates.
The existing 20-second and 256-KiB [transport limits](transport-v1.md) apply.

Event charts apply these same documented conventions to weddings, business
founding, adoption, purchases or other supplied events. This neither turns an
entity into a human natal profile nor establishes astrological causation.

## Context facts and interpretation

The application-only `LinkedReading` packet identifies up to three roles: `self`,
`other`, `event`; up to three pair comparisons; current canonical source UUIDs
and revisions; birth/event chart conventions; traditional house topics; and the pinned method metadata. Sources
come from the authenticated owner's records, never MCP/model/retrieval text.
No raw birth/calendar/coordinate input enters this packet. Current supplied
calculation facts enter existing SecondContext `instructions`, not explicit memory
ingestion. The v1 HTTP response API remains compatible.

A requested compatibility rating can carry `oria-reflection-rating-1`:
for self/other aspects, weights are trine +1, sextile +0.75, conjunction +0.25,
square −1 and opposition −0.75. Each is weighted by `7 − orb`. The score is
`round(5 + 3 × weighted_balance, 1)` on a ten-point interpretive scale. The present
formula yields 2–8; no aspects means no rating. The rating is supplied only when
the user asks to rate/score compatibility. It is a documented symbolic reading
convention, not an astronomy result, salience ranking, calibrated probability,
empirical compatibility measurement or relationship verdict.

House-topic tags 1–12 are retrieval and interpretation metadata. They cannot
establish a placement, overlay, causal connection, intention or outcome. Measured
features remain current per-turn inputs, never facts inferred from an old reading.
