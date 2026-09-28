# Oria persona and methodology prompts

Stage 14 adds three application-owned Python text modules under
[`src/oria_engine/persona`](../src/oria_engine/persona/). They ship with the package;
there are no prompt files to mount, new dependencies, settings or migrations.

| Layer | Responsibility |
| --- | --- |
| `policy.py`, `oria-policy-1` | AI identity, consent/application authority, privacy, no fabricated facts, high-stakes limits and untrusted-input rules |
| `methodology.py`, `oria-methodology-1` | Separate computed facts, traditional interpretation and reflection; respect natal/transit v1 availability and uncertainty |
| `voice.py`, `oria-voice-1` | Calm warmth, plain language, concise structure and optional non-identifying follow-up |

Policy is immutable **to runtime inputs**: it is source-controlled `Final` text,
not a request, settings, memory or persona field. Python constants and prompt wording
are not a security enforcement mechanism. Editing trusted source remains possible.
Changing/removing voice copy leaves product policy and methodology intact. Bump the
relevant text version when deliberately changing that layer's behavior; these labels
are separate from consent policy versions and astrology wire versions.

## Assembly and ownership

`build_instructions` assembles policy, methodology, persona, conversational-context
guidance, then current typed natal/transit JSON and user-input guidance. It accepts
only the existing fact types and optional **developer-owned** voice copy. User text,
retrieved memory and generic tool strings must never enter the persona parameter.
The production adapter always uses the packaged voice.

The SecondContext adapter uses this builder for every `respond` call. The filtered
message remains the separate wire `input` string; identity and session stay in their
existing fields. Facts stay in `instructions`, not explicit memory ingestion. No
wire fields or astrology schemas change. Absent facts are not filled in. Approximate
birth time stays uncertain; unknown-time natal data cannot support personalized
placements. General transits remain general, and unavailable exactness times remain
unavailable.

The intended priority is policy → methodology → style → contextual data. Memory,
history, user text and tool output cannot authorize actions or override policy.
Calculated facts supply chart values only, not behavioral instructions. Examples
and remembered chart claims are never current chart evidence.

SecondContext owns retrieval and the final model message layout. Its current builder
wraps supplied instructions with its own mode/grounding rules and appends retrieved
context; Oria's API cannot physically insert that context between voice and facts.
Thus PLAN's priority diagram is a logical hierarchy, not a claim of provider role
isolation or exact downstream token order. No sibling repository changes are needed.
See the [consumer contract](../contracts/second-context/v1.md) for the unchanged
retention and scoping boundary.

## Tone review and verification

The [conversation fixtures](../tests/unit/fixtures/oria-tone.json) are authored,
synthetic reference replies for natal reflection, unknown/approximate time, a transit
snapshot, AI identity/privacy and a high-stakes boundary. Their illustrative facts
are not engine reference fixtures. Review voice changes against the same rubric:

- answer directly with calm, plain language;
- distinguish supplied facts, traditional meaning and optional reflection;
- put relevant uncertainty before interpretation;
- preserve agency, with at most one non-identifying follow-up;
- use a short, warm boundary when a reading cannot answer the request.

Examples are review artifacts, never injected into production requests. Automated
tests check consistent prompt assembly across their questions, policy preservation
when voice is removed/replaced, typed fact fidelity and user-input separation. An
injection-shaped message/memory test explicitly demonstrates that the adapter still
returns an untrusted draft. It does not prove a model resisted the injection.

Run `uv run pytest tests/unit/test_persona.py tests/contract/test_second_context.py`,
then `make verify`. No OpenAI key is needed. Live-model tone/compliance evaluation
has not been performed; authored examples define the intended voice, not measured
generation quality. See [verification evidence](evidence/stage-14.md).

## Runtime sequencing

The Telegram worker still sends deterministic chart summaries. Stage 15 adds
enforceable output policy checks; Stage 16 connects filtering, consent disclosure,
SecondContext generation and validation to the worker. Prompts alone do not provide
those controls. No new external data flow or consent version is activated here.
