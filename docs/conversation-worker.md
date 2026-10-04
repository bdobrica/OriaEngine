# Complete conversation worker

The production job now injects `ConversationContext(SecondContextProvider(...))`
into the existing consent/onboarding flow. The job owns and closes the HTTP client.
All consent, profile, queue, locking and delivery invariants in
[worker queue](worker-queue.md) still apply. There are no migrations, dependencies,
new model tools or wire-schema changes.

After consent, a confirmed profile with a current derived cache permits active
chat. Onboarding, callbacks and profile/privacy commands remain deterministic and
never reach SecondContext. Active chat uses the scoped cache without decrypting
the birth profile. Follow-ups include current natal facts; date/current-transit
requests additionally calculate transit facts. Missing transit facts cannot be
reconstructed from memory. Ambiguous dates and recognized high-stakes requests
receive local replies. The optional context-free flow remains useful for tests
and deterministic consumers; the production worker always injects context.

Before generation, the conservative English input gate rejects the entire message
if it recognizes identifying categories, common volunteered birth/name/location
phrases, email/URL markers, phone-like numbers or street addresses. It forwards no
part of a rejected message. One ISO date remains usable as a transit target.
Unlabeled names/places, other languages and encoded values can evade this lexical
gate; it is not a guarantee of PII removal. Do not send private details in active
chat. No saved birth fields are loaded for comparison or sent to the provider.

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

Use `ORIA_POLICY_VERSION=2026-10-03.2` consistently in polling and workers. Bump custom
policy versions as well. Existing users must accept the new disclosure. It describes
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
the Stage 14 questions, prints synthetic draft/guard results for human review, and
attempts authenticated cleanup of its disposable subjects. Local privacy/safety
cases never call the model. No live provider is required for CI. See
[Stage 16 evidence](evidence/stage-16.md) for verification and the reviewed sample.
