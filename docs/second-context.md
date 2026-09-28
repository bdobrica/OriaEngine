# SecondContext adapter

The Stage 12 foundation provides `ContextProvider`, the HTTP implementation
`SecondContextProvider`, `ConversationContext` consent fencing, and stable
PostgreSQL session mapping. See the [versioned consumer contract](../contracts/second-context/v1.md)
for requests, responses, authentication, privacy, retry and deletion semantics.

Apply migration `0007` using `make migrate`. It adds `conversation_sessions` with
one row per internal user: owner UUID, unique external session UUID, creation time.
There are no messages or chart facts in this table. Session IDs use UUIDv5 with the
user UUID as namespace and `oria-session-v1` as name, so a database rollback after
a remote write cannot cause a new external session on retry. Downgrading removes
only these mappings; it does not delete SecondContext data.

Use `ConversationContext.respond(session, user_id, request)` or `.remember(...)`
inside a caller-owned `Database.transaction()`, with the trusted internal UUID
from ingress. Each operation locks the live user, checks the latest consent against
the configured policy and gets/creates the mapping before HTTP. The lock fences
concurrent withdrawal. Repositories flush but do not commit. Scope objects are
internal plumbing, not credentials or permission to accept a user-selected UUID.
The adapter owns an async HTTP client; call `aclose()` on shutdown.

`ConversationRequest.filtered_message` is an explicitly application-filtered active
message, **not** a PII detector. Onboarding and raw profile inspection must never be
routed here. The typed facts slot accepts only the derived natal result. Semantic
memory accepts fixed phrases for concise readings, less mystical language, explicit
uncertainty and selected prior topics; it cannot accept arbitrary birth details.
Current facts are supplied in instructions only. Upstream transcripts still persist
user and assistant text, including any facts repeated in a generated answer.

## Runtime status and remaining dependencies

The polling/worker demo does not call this adapter yet. Stages 13–16 add active
routing, filtering, prompt/persona assembly, output validation and worker wiring.
Before enabling external conversation storage, update the consent/privacy disclosure
to describe actual SecondContext retention and the available deletion controls.
The current policy version remains unchanged because the live flow sends no new data.

The inspected sibling SecondContext checkout lacks subject-wide purge, and its
bearer tokens bind to individual subjects. A shared token cannot support multiple
Oria UUIDs. The adapter preserves those restrictions and fails explicitly for purge.
Upstream work is required before Stage 12's purge acceptance criterion can pass.
Changing authentication delegation needs an explicit security decision in the owning
repository; Oria must not bypass it with direct database access or a default user.

No live-provider call is necessary for tests. The reusable HTTP stub in
`tests/support/second_context.py` checks identity/session isolation and holds only
synthetic preferences. It demonstrates adapter continuity but is not evidence that
a deployed SecondContext instance, embeddings, retrieval or live LLM works.
Run `make test-contract` for HTTP tests, `make test-integration` for real PostgreSQL
session/migration/consent tests, and `make verify` for the full gate.
