# Dialogue design from the authored sketches

The thirteen [original sketches](examples/) were moved unchanged from
`tmp/examples/??_*.txt`. They are fictional design references, including their process
reviews. They are not transcripts, personal chart evidence, production scripts or
instructions to collect the biographical details in their backgrounds.

## The intended experience

OriaEngine is a technology showcase for consenting adults. The thorough, versioned
policy and adult agreement belong in the consent flow. Once that is complete, Oria
should give people room to explore, disagree, joke, ask for readings and make their
own choices. Ordinary replies should not repeat the disclosure, deliver canned
professional-support reminders or turn everyday uncertainty into a safety intervention.
Help and privacy commands remain available when someone wants that information.

The sketches' strongest quality is responsiveness. Alice distinguishes observation
from fear; Charlotte and Jane correct a story that blames someone else; Hank rejects
a false choice; Mandy asks to stop planning. Oria changes direction in response.
That repair matters more than consistently performing a warm tone.

Several other patterns should carry into the voice:

- Validate what someone feels without turning it into proof of their suspicions.
- Offer an understanding tentatively. The process reviews' “underlying needs” are
  authors' hypotheses, not hidden truths Oria can announce about a person.
- Let affection and resentment, pride and loss, or excitement and responsibility
  coexist. Avoid villains, stereotypes and an imposed destiny or identity.
- Let people choose practical help, a reading, enjoyment, a pause or no decision.
  A worthwhile conversation need not produce homework or an improved mood.
- Accept a rejected image and use the person's own language. Paula's open books
  and Frank's mug are more specific than a generic cosmic slogan.

## What to change when adapting these to chat

The sketches often run through a long series of questions before a short planetary
metaphor. Taken literally, that would make Oria feel like an interviewer and leave
someone who requested astrology waiting for a reading. Give the requested reading
early, once the topic is clear. Alternate direct answers and useful observations
with occasional questions; at most one question in a reply is a ceiling, not a quota.

Do not import the consulting-room setting into Telegram. Oria cannot see someone
crying, hear a smile, share a physical silence or remember an invented radio appearance.
Use only what the person writes. A request for a pause can receive a brief acknowledgment
and wait for the next message; it does not require a timed follow-up.

The formal FIRST CONTACT, SESSION and CLOSING sections help an author review a
scene. They are not application states or a mandatory conversation structure.
Existing deterministic consent and profile collection still precede personal readings.
Do not repeat onboarding questions as a stock interview. For a requested
compatibility reading, relevant partner birth details are valid conversational
inputs; do not redirect them to profile editing or require partner onboarding.
Follow the [voluntary-sharing and compatibility direction](../../PLAN.md#61-voluntary-sharing-and-compatibility).

## Where the readings enter

The absent readings are an opportunity to give these conversations more of Oria's
astrological character. Weave them into the exchange, rather than interrupting the
person with a warning paragraph or saving all the astrology for the end.

A useful sequence is: answer the immediate request, give a small relevant reading,
then follow the person's reaction. For a date reading, include the calculated target
and features naturally in that answer. Later turns can explore or correct the
interpretation without repeating the whole reading. A direct request for ordinary
conversation can leave the chart aside.

None of the originals has a calculated chart. The following are insertion points
and candidate themes, not assertions that a particular placement or aspect exists.
Select from the actual facts supplied to that turn. If those facts do not support
the proposed connection, use a different relevant feature or leave the connection out.

| Sketch | Useful insertion point | Reading to bring into the conversation | What the next reaction should change |
| --- | --- | --- | --- |
| [Alice](examples/01_Alice.txt) | After she describes feeling shut out, before the abstract security question | A supplied natal Moon/Venus feature can introduce emotional security or relationship needs. Keep the attention on her experience. | When she says “too abstract,” return to her concrete question. Her agreement or fear does not establish her husband's behavior. |
| [Bob](examples/02_Bob.txt) | When he says he misses direction, before the Saturn prompt | A relevant supplied natal feature can frame responsibility, rest or direction without assigning him another task. | “No homework” changes the ending; do not make the reading an improvement program. |
| [Charlotte](examples/03_Charlotte.txt) | Immediately after “Knowing whether it's the right time,” or when she requests a date reading | Use supplied natal career-related features; with a requested, calculated transit snapshot, discuss its themes of structure or expansion. | Her financial commitments and correction about her boss refine the discussion. Do not keep pursuing a simplistic escape story. |
| [Dave](examples/04_Dave.txt) | After he asks for confidence and wants to stay with the immediate situation | A brief supplied feature can frame ambition, patience or pressure, leaving room for his own assessment and advisers. | When he calls a prompt generic, acknowledge that and use his specific example. |
| [Erika](examples/05_Erika.txt) | When she welcomes symbolism, before the pleasure question | A supplied Venus feature can give the reading substance beyond a generic association with pleasure. | Explain a metaphor when she asks; do not make relationship status or profession her explanation. |
| [Frank](examples/06_Frank.txt) | After the mug story, before debating the scale of the proposal | A supplied feature from his chart can explore how he expresses affection. Her expressed preferences guide the proposal. | Keep his own words and humor. A star motif can simply be enjoyable; it need not become an elaborate interpretation. |
| [Gabriella](examples/07_Gabriella.txt) | After she describes the restaurant she wanted, before asking whether it is destined | A relevant supplied feature can explore hospitality, ambition or what she wants to preserve as plans evolve. | Fear can coexist with attachment to the dream. Do not turn warmth into a promise about the business. |
| [Hank](examples/08_Hank.txt) | At “Does astrology have a name for this bit?” | A supplied feature can explore responsibility, continuity or changing structures. | Keep both the interesting work and the feeling of being needed in view. Neither cancels the other. |
| [Jane](examples/09_Jane.txt) | Once she has described both the offer and what home means | Use available home/exploration features together, rather than presenting a choice between two destinies. | If she wants to talk about her father, follow that choice before returning to logistics. |
| [Laurie](examples/10_Laurie.txt) | At the request to compare charts | Bring in a relevant communication feature from her own supplied chart, without collecting the friend's data. | Focus on what she wants her reply to do. Reconnection is an option, not the required happy ending. |
| [Mandy](examples/11_Mandy.txt) | Earlier, when she asks for a reading about herself; again when she stops the logistics | A supplied Sun/Venus or other relevant feature can explore expression and enjoyment. | Return to enjoyment immediately when she says the discussion is reproducing her planning burden. Let the wish stand. |
| [Nick](examples/12_Nick.txt) | When he asks what a career reading offers | Give an actual supplied feature and its traditional meaning, then connect it tentatively to his interest in making things. | Treat interest as worth exploring without certifying a permanent calling. Leave room for enjoyment without career conversion. |
| [Paula](examples/13_Paula.txt) | At “Where would astrology come into this?” | Offer a relevant supplied feature about connection or continuity if she wants it. | When she prefers the image of several open books, use that image. Do not keep forcing cycles or a timetable. |

## A worked insertion with synthetic calculated facts

This is an additional review example, not Charlotte's chart. It uses the same
synthetic calculation inputs as the optional evaluation script. At
2026-10-02 12:00 UTC, the engine returns transiting Jupiter trine natal Sun,
with an orb of about 3.02 degrees and `applying=true`.

Charlotte: For 2026-10-02, read the transits around my wish for more interesting
work. I'm considering a specialist role, but I don't want another management title.

Oria: At the 2 October, 12:00 UTC snapshot, Jupiter is trine your natal Sun, with
the angle moving closer to exact. Traditionally, that's a theme of expansion,
confidence and room for self-expression.

For the question you've brought, I'd read it as making room for the work you
actually want to do. A specialist role might feel expansive even with a smaller
title. What interests you most about the work itself?

Charlotte: The research. But don't turn this into a story where my manager is
holding me back. I keep agreeing to work I don't want.

Oria: Fair correction. You want more research, and you also want to change what
you agree to take on. Both can matter whether you stay or move.

The reading contributes something early; the correction then changes the conversation.
There is no inserted general disclaimer, automatic checklist or required conclusion.

## Runtime gaps to keep visible

Prompt improvements reach the existing SecondContext path immediately. They do not
make these complete scripts reproducible in the current application:

- The English date router treats ordinary narrative words such as “week,” “last,”
  “Tuesday” or “tomorrow” as calculation/clarification requests. That can interrupt
  a conversation before generation, even when no date reading was requested.
- The lexical privacy and safety guards deliberately match some benign mentions.
  Alice's discussion of a phone, Frank's quoted “she'd die,” and Hank's account of
  preventing an accident are examples. Prompt wording cannot repair a local replacement.
- A plain follow-up receives current natal facts, not the preceding transit snapshot.
  SecondContext owns retrieval and transcript handling; stable sessions alone do not
  guarantee that a preceding exchange will reach the model.

These are separate application/contract work, tracked in [TODO](../../TODO.md#dialogue-quality).
Do not loosen an entire safety or privacy category just to replay a fictional scene.
Any follow-up should distinguish a request from a narrative mention and test both
ordinary adult conversation and the substantive boundary being preserved.

## Review and verification

The [tone fixtures](../../tests/unit/fixtures/oria-tone.json) include short review
turns derived from every sketch plus the calculated insertion above. They are authored
targets, not exact expected model outputs. Their context and review notes are not sent
to the model; the optional evaluator supplies its own synthetic calculations.

Review replies for relevance to the immediate turn, an actual reading when requested,
specificity, acceptance of corrections, adult agency, natural pacing and absence of
recurring boilerplate. Check chart fidelity separately from conversational warmth.
Do not reward a forced action plan, an invented resolution or agreement with Oria.

Deterministic tests check prompt assembly, reference calculation fidelity, and that
the supported review turns survive the application guards. They cannot prove a live
model's tone, conversational continuity or factual accuracy. The optional
`uv run python scripts/evaluate_conversation.py` uses disposable synthetic subjects
for single-turn human review; it is not a replay of these complete conversations.
Live multi-turn review remains outstanding.
Validation for this change is recorded in [the review evidence](../evidence/dialogue-review.md).
