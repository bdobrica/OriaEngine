# Transit calculations and active-message routing

After onboarding, the Telegram worker can answer `Explain my natal chart`,
`transits today`, and `transits on 2026-10-02` with readable calculated facts.
Use the existing [worker setup](worker-queue.md), rebuild with `make mcp-local`,
and restart `make worker`. No new dependency, configuration, migration or OpenAI
key is required. Existing natal caches remain valid.

These are deterministic fact summaries. Persona, broader policy checks and LLM
interpretation remain Stages 14–16. The worker does not call SecondContext yet.
The English rule router needs no LLM classifier for this baseline. Unrecognized
questions take the `follow_up` path and ask the user to restate a supported topic;
there is no guessed previous transit date or implicit tool authorization.

## Routing and date conventions

`ActiveIntent` is a private typed application schema with these paths:

| Intent | Facts and behavior |
| --- | --- |
| `natal_explanation` | Reuse the valid derived natal cache; no MCP call |
| `current_transits` | Calculate a snapshot at the inbound message's UTC timestamp |
| `transits_for_date` | One explicit `YYYY-MM-DD`, at 12:00 UTC |
| `follow_up` | Ask for the topic; no new calculation |
| `unsupported_high_stakes` | Fixed bounded response; no calculation or model call |
| `clarify_date` | Request one ISO date or “today”; no calculation |

Current snapshots use the persisted message timestamp, so queue delays and retries
do not silently select another instant. “Today” is a snapshot, not a local-day
forecast. Date-only requests explicitly display the noon-UTC convention; it is
not an approximation of the user's birth time. No current location/timezone is
collected or inferred from birthplace. Supported target years are 1800–2399.

Slash commands and onboarding callbacks retain their existing handlers. The
router gives recognized high-stakes requests priority over dates and chart terms.
Multiple, invalid, slash-formatted or incomplete dates and unsupported relative
dates/times ask for clarification. The user can reply with a complete ISO date;
no separate pending clarification state is needed. This bounded rule vocabulary
is not a general natural-language parser or the Stage 15 safety classifier.

Consent, the user lock, completed onboarding and cache validity gate active work.
Active questions load only derived facts, without decrypting the birth profile.
Edits/stale caches return through the existing profile recovery path. Transit
failure returns a generic retry message without replacing the natal cache.
Calls are bounded to 20 seconds inside the existing worker deadline. The queue
commits the encrypted reply before delivery and resends it after a send failure
without recalculation. There is no persistent transit cache or new database state.

## Transit MCP v1

`calculate_transits(request)` is an additive tool beside the unchanged natal tool.
The published [transit JSON schema](../contracts/astrology/transits-v1.json) is
generated from [transits.py](../src/oria_engine/astrology/transits.py) by
`uv run python scripts/generate_astrology_schema.py`. The existing natal v1 schema,
engine version and reference fixture are unchanged.

The request contains a target UTC instant, natal accuracy and ten unique
`{body, longitude}` natal references, or an empty reference list for unknown birth
time. It accepts no identity, date/time of birth, coordinates, place name, speed
of natal bodies or arbitrary options. OriaEngine supplies only a current,
consent-scoped derived cache. The stateless MCP service does not authorize users.

The response includes ten transiting positions, signs, degrees, longitude speeds,
retrograde flags, natal-to-transit aspects and explicit availability/provenance.
Astronomy uses the same pinned Moshier/Swiss Ephemeris conventions and supported
bodies as [natal v1](astrology-mcp.md). `oria-transits-1` identifies the new feature
engine independently of the unchanged `oria-natal-1` astronomy baseline.

Each aspect uses **body_a = fixed natal**, **body_b = transiting**, including
same-body pairs. Every ordered natal/transiting pair is considered once. Relative
velocity equals the transiting longitude velocity: the natal reference has zero
motion, regardless of its original birth-time speed. The shortest angular
separation, major aspect targets, inclusive 6° orb and applying/separating
derivative follow natal v1. Exactness, separation cusps and near-stationary motion
return null applying state under its `1e-8` thresholds. Measurements retain full
precision; display rounding does not change classification.

`time_to_exact_hours` is null, availability is false, and the method is explicitly
`unavailable`. No linear extrapolation or solved crossing is claimed. Transit
houses and angles are not calculated. Approximate birth time marks natal
relationships uncertain. Unknown birth time still permits target-time planetary
positions, but returns no natal relationships; the reply labels these general
positions as unpersonalized.

## Future interpretation boundary

`prepare_active` returns only the facts selected for the route: natal or transit,
neither for clarification/follow-up/high-stakes responses. `ConversationRequest`
now accepts an optional typed `transit_facts` alongside existing `natal_facts`.
The SecondContext adapter includes them in instructions only, with existing
untrusted-data guidance, never explicit memory ingestion or identity metadata.
No raw birth inputs are added. A transit target timestamp is not a birth timestamp.
Transcript/provider retention caveats in the [consumer contract](../contracts/second-context/v1.md)
still apply. Filtering, persona, output policy validation, contextual follow-ups
and worker activation of that adapter remain later stages.

See [Stage 13 verification](evidence/stage-13.md).
