# Oria persona and methodology prompts

The adult conversation policy, methodology and memory guidance accept useful
volunteered context and broad discussion. They distinguish harmful responses from
topic mentions and explain unimplemented event memory, selective erasure and partner
calculations honestly. The [remaining design](conversation-memory-plan.md) and
[candidate contracts](../contracts/knowledge/v1.md) do not authorize model-driven
mutations or enable those future capabilities.

Stage 14 adds three application-owned Python text modules under
[`src/oria_engine/persona`](../src/oria_engine/persona/). They ship with the package;
there are no prompt files to mount, new dependencies, settings or migrations.

| Layer | Responsibility |
| --- | --- |
| `policy.py`, `oria-policy-6` | AI identity, consent/application authority, privacy, substantive safety limits, adult agency and untrusted-input rules |
| `methodology.py`, `oria-methodology-5` | Weave relevant calculated readings into dialogue; separate facts and interpretation and respect availability and resolved targets |
| `voice.py`, `oria-voice-2` | Natural adult conversation, specificity, acceptance of corrections, optional questions and user control of pace |

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

OriaEngine's thorough policy disclosure and explicit adult agreement belong in the
application consent flow. Ongoing dialogue should feel free and natural: answer the
requested reading, respect adult judgment and avoid moralizing, unnecessary refusals,
repeated disclaimers and canned professional-support reminders. A specific missing
fact can be explained where it affects the answer. A substantive boundary remains
brief and relevant to the actual request; it is not a reason to add routine warnings.

The [dialogue review guide](dialogue/README.md) analyzes all thirteen authored sketches,
identifies reading insertion points and includes a synthetic calculated example.
It also records runtime routing/guard/continuity gaps that prompt changes cannot fix.
Original scenes remain review artifacts; their consulting-room setting and background
biographies do not become runtime instructions or evidence about a user.

The [conversation fixtures](../tests/unit/fixtures/oria-tone.json) are authored,
synthetic reference replies for natal reflection, unknown/approximate time, a transit
snapshot, AI identity/privacy, an uncertainty discussion and a short turn from each new
sketch. Their illustrative facts
are not engine reference fixtures. Review voice changes against the same rubric:

- answer the immediate request with calm, specific, plain language;
- distinguish supplied facts, traditional meaning and optional reflection;
- put relevant uncertainty before interpretation;
- accept corrections, preserve adult agency and ask at most one relevant
  follow-up, without requiring a question or an action plan in every reply;
- bring requested readings into the conversation without recurring boilerplate;
- use a short, warm boundary when a reading cannot answer the request.

Examples are review artifacts, never injected into production requests. Automated
tests check consistent prompt assembly across their questions, policy preservation
when voice is removed/replaced, typed fact fidelity and user-input separation. An
injection-shaped message/memory test explicitly demonstrates that the adapter still
returns an untrusted draft. It does not prove a model resisted the injection.

Run `uv run pytest tests/unit/test_persona.py tests/contract/test_second_context.py`,
then `make verify`. No OpenAI key is needed. Live-model tone/compliance evaluation
is recorded separately in [Stage 16 evidence](evidence/stage-16.md); authored examples
define the intended voice. See also [Stage 14 evidence](evidence/stage-14.md).

## Runtime sequencing

The [conversation worker](conversation-worker.md) connects input filtering, updated
consent disclosure, SecondContext generation and application output policy checks.
Prompts alone do not provide those controls.
