# SecondContext adapter

Optional [linked context](linked-context.md) uses SecondContext for salience and
interpretations while canonical encrypted events/entities stay in Oria. The
[versioned projection lifecycle](../contracts/knowledge/v1.md) adds verified
capability, revision-aware delivery, linked retrieval and selective erasure.
The fixed memories and subject purge below remain separate compatible APIs; do
not bypass them with arbitrary memory text or direct database access.

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
its deployment/provider setup. `make dev` does not start that service. The
[published-image deployment](deployment.md) includes it by default using the
migration-enabled gateway image from commit `b1a58486218df138af456126fe7514a9f5b60cdd`
(release `0.1.1` or compatible later). Its own migration job uses the
`secondcontext` database and restricted role on the shared PostgreSQL server;
Qdrant remains separately owned. Select `DEPLOY_FILE=deploy/compose.oria.yaml`
for an existing external instance. Neither mode requires its source checkout at
runtime. OpenAI credentials stay in its runtime environment.

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

The updated disclosure uses policy version `2026-11-10.1`; deploy it consistently and
bump custom versions before enabling conversation storage. It describes actual
SecondContext retention and deletion controls, including the minimal deletion marker.

The reusable HTTP stub in `tests/support/second_context.py` exercises consumer-side
scope, continuity and strict purge parsing. The [Stage 12 evidence](evidence/stage-12.md)
records upstream API, PostgreSQL and Qdrant tests with synthetic LLM responses.
Oria's verification gate does not run that sibling repository's suite.
No real OpenAI/Telegram calls or operator database changes are required.
Run `make test-contract` for adapter tests,
`make test-integration` for Oria's database tests, and `make verify` for the full gate.

## Optional linked life-event memory

[Linked context](linked-context.md) adds a separate `linked-context-1` projection
lane, migration 000004 in SecondContext and 0012 in Oria. It is disabled by default;
The published `0.2.1` gateway includes this capability; the `0.1.1` baseline does not.
After a compatible release, use `SECOND_CONTEXT_KNOWLEDGE_ENABLED=true`, scoped
service authentication and disclosure 2026-11-10.1. The owning-service contract
adds only explicit knowledge upsert/query/delete/capabilities routes and optional
`knowledge_refs` on responses. Legacy response, fixed-memory and purge behavior
remain compatible. Selective cleanup retries after withdrawal/disablement.

## Accepted conversation-history work (not enabled)

The [history consumer contract](../contracts/second-context/conversation-history-v1.md)
records OCH1 requirements for replay, prepared local exchanges, accepted replies and
delivery, including a new disclosure version and fresh acceptance before rollout.
The current runtime and policy version are unchanged; OCH2/OCH3 implement this next.
