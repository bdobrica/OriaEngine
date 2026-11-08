# Complete conversation worker

The production job now injects `ConversationContext(SecondContextProvider(...))`
into the existing consent/onboarding flow. The job owns and closes the HTTP client.
All consent, profile, queue, locking and delivery invariants in
[worker queue](worker-queue.md) still apply. Migration `0010` adds encrypted temporary
date clarification. There are no new dependencies, model tools or live wire-schema
changes. Candidate long-term event contracts remain inactive.

After consent, a confirmed profile with a current derived cache permits active
chat. Onboarding, callbacks and profile/privacy commands remain deterministic and
never reach SecondContext. Active chat uses the scoped cache without decrypting
the birth profile, except explicit own-birth anchors resolved locally. Follow-ups
include current natal facts; date/current-transit
requests additionally calculate transit facts. Missing transit facts cannot be
reconstructed from memory. Relative targets use the explicit current timezone
preference and recorded ingress timestamp. Missing timezone preferences, ambiguous
dates and recognized harmful requests
receive local replies. The optional context-free flow remains useful for tests
and deterministic consumers; the production worker always injects context.

Before generation, the input gate holds obvious account secrets locally while
allowing voluntary personal context. [Typed natural dates](current-time.md) distinguish
event/birth/anniversary context from transit requests and profile corrections.
Unfinished questions are encrypted for up to 24 hours against the original reference;
replies can supply a timezone, date, occurrence year or clock after restart. Explicit
own-birthday references can read the local saved date; partner input cannot select
another account. Withdrawal/deletion clear pending state.

Birth-bearing clauses and obvious continuations are withheld before model processing;
other clauses and resolved non-birth temporal context remain useful. The service
repeats input preparation for direct callers. This bounded English preparation
can still lose nuance or miss unlabeled/encoded inputs. No raw saved birth fields
or typed birth candidates are forwarded. See the [policy](response-policy.md) and
[remaining storage work](conversation-memory-plan.md).

The guarded application service rechecks consent and uses a stable user/session
scope before the adapter assembles policy, methodology, voice, typed facts and
filtered input. Retrieved context belongs to SecondContext. Output policy replaces
unsafe drafts locally. Replies exceeding Telegram's 4096 UTF-16-unit bound receive
a fixed request for a shorter reading. The encrypted validated reply commits with
local state, then Telegram delivery rechecks consent. No arbitrary memory ingestion
or model-driven profile mutation is introduced.

## Failures and remote effects

Active MCP and context failures propagate to the existing five-attempt queue retry
budget with durable exponential backoff. The final typed downstream failure rolls
back partial domain work and commits a fixed temporary-unavailability reply. Errors
retain only bounded codes. The context request has a 20-second
deadline; the complete worker attempt remains bounded at 60 seconds. Telegram
delivery failures reuse the saved validated reply without repeating generation or
transit calculation. Profile removal or user deletion before processing prevents
old queued text from using a stale chart or context scope. A running operation
holds the user row lock; withdrawal/deletion waits for that operation to finish.

The [abuse controls](abuse-controls.md) bound each user's admission/backlog and both
downstream response sizes. `LLM_PROCESSING_ENABLED=false`, followed by restarting
all workers, disables new generation and memory ingestion while preserving
deterministic commands and deletion. Running calls and committed replies may finish.

SecondContext has no response idempotency key. Worker retry after a lost response,
timeout, or crash before the local reply commit can repeat remote transcript writes
and generation. The stable session prevents scope proliferation, **not duplicate
transcripts**. This is an at-least-once integration; only local domain mutations
and retries after a committed reply have durable deduplication. No exactly-once
remote guarantee is claimed. Adding remote idempotency requires an owning-service
contract extension. See the [consumer contract](../contracts/second-context/v1.md).

## Demo setup

Use `ORIA_POLICY_VERSION=2026-11-08.2` consistently in polling and workers. Bump custom
policy versions as well. Existing users must accept the new disclosure. It describes
voluntary personal context, user/storage responsibilities, birth-clause withholding,
temporary date clarification and local own-birthday access,
SecondContext/AI processing and retention, quoted chart facts, retained blocked
drafts, limited filtering, and confirmed account deletion. Decline stops
further processing but does not purge previous data. Confirmed deletion retains a
minimal subject/timestamp marker; backups/provider retention remain separate.

Start SecondContext using its own deployment instructions, then configure
`SECOND_CONTEXT_BASE_URL` (for a host-run demo, typically `http://localhost:8080`).
For service authentication use the [adapter setup](second-context.md). Keep OpenAI
credentials in SecondContext, not Oria. Run `make infra-up`, `make migrate`,
`make mcp-local`, `make worker`, then `make run` in another terminal. Ask about a
natal chart, transits today, or a target date after completing onboarding.

`uv run python scripts/evaluate_conversation.py` is an optional paid live review
against the configured SecondContext. It uses only synthetic calculated facts and
the tone questions and short review turns from the [dialogue sketches](dialogue/README.md),
prints synthetic draft/guard results for human review, and
attempts authenticated cleanup of its disposable subjects. Local privacy/safety
cases never call the model. No live provider is required for CI. See
[Stage 16 evidence](evidence/stage-16.md) for verification and the reviewed sample.
This evaluator reviews isolated turns, not complete multi-turn conversation replays.
