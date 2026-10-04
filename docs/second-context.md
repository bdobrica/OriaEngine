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
routed here. Typed facts slots accept derived natal and transit results, including
the transit target timestamp but no raw birth fields. Semantic
memory accepts fixed phrases for concise readings, less mystical language, explicit
uncertainty and selected prior topics; it cannot accept arbitrary birth details.
Current facts are supplied in instructions only. Upstream transcripts still persist
user and assistant text, including any facts repeated in a generated answer.

## Service setup and deletion

Use SecondContext revision `4bb8dba86e7f91cb49db6b9c6aad311d03b57099` or a
compatible later release. Apply its migration `000003` and configure
its runtime with `AUTH_ENABLED=true` and `AUTH_SERVICE_TOKENS=oria:=<service-secret>`.
Use the same secret in Oria's `SECOND_CONTEXT_BEARER_TOKEN`, and set
`SECOND_CONTEXT_SUBJECT_NAMESPACE=oria`. Keep secrets in runtime configuration;
no OpenAI key is needed for the test suites. `SECOND_CONTEXT_BASE_URL` points to
the private SecondContext API, as before.

For `make dev`, also set `SECOND_CONTEXT_DOCKER_URL` to a container-reachable API
address; the [Docker guide](development.md#configuration) explains host bridging.
The owning repository's [README](https://github.com/bdobrica/SecondContext) supplies
its deployment/provider setup. OriaEngine does not start that service or require
its source checkout at runtime. OpenAI credentials stay in its runtime environment.

The namespace is opt-in: leaving it empty preserves existing plain UUID scopes
and ordinary subject-bound token behavior. With `oria`, the external subject is
`oria:<internal UUID>` and each HTTP request gets its own `X-SecondContext-Subject`
header. Keep this identity configuration stable; switching namespaces does not
migrate data and may conflict with existing globally unique session identifiers.

`SecondContextProvider.purge(user_id)` calls the authenticated versioned subject
purge endpoint and validates the exact subject and completed acknowledgement.
Failures never count as deletion success; callers retry the same UUID. The owning
service erases canonical content and the active vector index, retaining a minimal
subject/timestamp marker to fence delayed writes. A returning deleted user needs
a fresh Oria UUID. Backups, retired indexes and provider retention have separate
lifecycles; deletion does not magically erase those copies.

## Runtime status

The adapter supports [active routing and transit facts](transits-and-routing.md),
[policy, methodology and persona assembly](persona-prompts.md),
[application output validation](response-policy.md), and
[input filtering and worker wiring](conversation-worker.md) through the guarded service.
The polling/worker demo calls this adapter for eligible active chat and
[confirmed, durable account deletion](deletion.md) across Oria and SecondContext.

The updated disclosure uses policy version `2026-10-03.2`; deploy it consistently and
bump custom versions before enabling conversation storage. It describes actual
SecondContext retention and deletion controls, including the minimal deletion marker.

The reusable HTTP stub in `tests/support/second_context.py` exercises consumer-side
scope, continuity and strict purge parsing. The [Stage 12 evidence](evidence/stage-12.md)
records upstream API, PostgreSQL and Qdrant tests with synthetic LLM responses.
Oria's verification gate does not run that sibling repository's suite.
No real OpenAI/Telegram calls or operator database changes are required.
Run `make test-contract` for adapter tests,
`make test-integration` for Oria's database tests, and `make verify` for the full gate.
