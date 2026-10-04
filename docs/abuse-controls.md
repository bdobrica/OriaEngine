# Rate limiting and abuse controls

Polling and webhook ingress use the same admission limits. Redis holds disposable
counters; PostgreSQL remains authoritative for pending work, consent, identity and
deletion. No dependency or migration is required.

| Control | Default / bound |
| --- | --- |
| New inbound updates per sender | `INBOUND_RATE_PER_MINUTE=20`, configurable 1–120 |
| Nonterminal events per internal user | `QUEUED_JOBS_PER_USER=8`, configurable 1–32 |
| Message text | 4096 UTF-16 units; malformed surrogate text rejected |
| Webhook body / admission | 256 KiB / 5 seconds |
| Whole worker attempt | 60 seconds |
| Astrology MCP / SecondContext request | 20 seconds each |
| MCP HTTP response, including JSON or SSE framing | 256 KiB, uncompressed |
| SecondContext decoded response | 256 KiB |
| Conversation response generation | `LLM_PROCESSING_ENABLED=true` |

## Admission and fairness

Admission checks accepted update receipts first. Replays reuse the UUID and do not
consume the rate budget or create an identity. New text exceeding the limit is
rejected before identity creation; text is never silently truncated. Before consent,
allowed text is still discarded under the existing privacy rule.

A Redis Lua script atomically admits up to the configured count during a 60-second
window starting with the first accepted update. Rejections do not extend the window.
The trusted provider sender scopes counters across gateway replicas and before a
new internal UUID exists. Redis failure fails admission closed: webhook returns the
existing controlled 503; polling keeps retrying the update until service recovery
or cancellation. A counter can remain charged if a later database step fails.

Under the existing short admission lock, PostgreSQL counts all nonterminal events
for the user, including delayed retries and saved replies. Concurrent gateways cannot
exceed the cap. Completion/expiry/deletion frees capacity. Redis loss resets rate
counters but cannot reset this cap. Lowering the cap does not erase existing work;
new admission waits until the backlog drains below it. Deterministic commands and
buttons use these same admission budgets; retry them after the window/backlog clears.

Only the earliest due event per user is published from ingress or the recovery scan.
Later events remain canonical in PostgreSQL. Recovery selects at most 100 user heads,
so one large pre-existing backlog cannot fill an entire scan. A Redis NX reservation
also suppresses repeated publication of the same UUID for 150 seconds. Failed enqueue
releases its own reservation; a claimed attempt releases it when finished. Unclaimed
or crashed jobs recover after expiry. Losing Redis removes these reservations and
recovery safely restores work. Completed/deleted receipts are never republished by
ingress. Existing Redis and PostgreSQL worker fences still permit one active attempt
per user while unrelated users proceed on the other worker threads.

Limits deliberately drop new excess messages instead of creating more queue work.
Webhook returns HTTP 200 to prevent provider retry amplification. At most one fixed
notice per sender per minute requests a shorter message or a later retry; it uses
Telegram's webhook `sendMessage`/`answerCallbackQuery` response mechanism. Polling
sends the same bounded notice directly. Notice delivery is best effort, with no new
outbound queue or retained rejected payload. Rejected updates have no durable receipt;
an unexpected later redelivery can be admitted once limits clear.

## Downstream failure and emergency stop

Existing canonical retries back off 10, 20, 40 and 80 seconds, with five attempts
shared across processing and sending. Duplicate jobs cannot bypass deadlines or
reset attempts. On the final typed astrology/context processing failure, a savepoint
rolls back partial domain work and the worker commits the fixed reply:
“I'm temporarily unavailable. Please try again in a little while.” It still passes
the normal owner/consent delivery fence. Failure to send on that final attempt can
exhaust the budget without a visible notice. Timeouts, unclassified failures and
delivery failures retain existing bounded dead-event handling. Confirmed-profile
calculation failures already return their deterministic correction/retry reply.

Set `LLM_PROCESSING_ENABLED=false` in private runtime configuration and **restart all
workers** to stop new generation. Configuration is read at process startup; already
running calls and already committed replies may finish. The application returns the
fixed unavailable reply without a SecondContext response or memory-ingestion call.
Profile/privacy commands, onboarding, calculations and authenticated subject purge
continue through their deterministic paths. No credential or policy bypass is added.

The MCP consumer bounds bytes before the SDK buffers/parses JSON or SSE. It requests
identity encoding and rejects compressed responses, preventing decompression from
bypassing that bound. The controlled astrology service uses uncompressed responses.
SecondContext retains its streamed decoded-byte bound and scoped result validation.
Both clients preserve cancellation and expose fixed errors without response data.

## Privacy and limits

Redis abuse keys are `oria:abuse:telegram:<numeric sender>:rate` and `:notice`, each
with a 60-second TTL. Publication keys are `oria:event:<internal UUID>:publication`,
with a 150-second TTL. No names, message text, birth data, chat IDs or credentials
enter these keys or values. Final account cleanup removes the exact sender rate/notice
keys under the shared admission lock before removing its identity. Unlinked event
publication reservations expire naturally; their jobs are inert after local deletion.

This protects the demo against one sender's backlog and repeated delivery. It is
not a global cost quota, multi-account/IP attack defense, strict tenant scheduling
at arbitrary deployment scale, or a global downstream circuit breaker. Keep the
existing private-service boundaries and authenticated webhook proxy configuration.
No live paid-provider or public Telegram load test is required by CI. See
[verification evidence](evidence/stage-20.md).
