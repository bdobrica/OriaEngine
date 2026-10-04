# Telegram webhook ingress v1

OriaEngine owns `POST /telegram/webhook`. Telegram supplies its Bot API `Update`
JSON; the boundary converts it to the existing internal `ChannelMessage`. No
SecondContext or astrology contract changes are introduced.

## Authentication and admission

Exactly one `X-Telegram-Bot-Api-Secret-Token` header must match the configured
`TELEGRAM_WEBHOOK_SECRET`, compared before reading or parsing the body. The secret
is a transport credential, never a user-selected owner identifier. Raw requests,
headers, validation errors and Telegram metadata must not enter diagnostics.

An authenticated body is limited to 256 KiB, including chunked bodies, and parsed
with the installed aiogram Update schema. Unknown additive fields are tolerated.
Supported events are ordinary private text messages and accessible private button
callbacks from humans. Existing [adapter normalization](../../docs/telegram.md)
determines sender identity and supported chat/event types. Edited messages, media,
business messages, group/channel events and unsupported callbacks are ignored.

Supported commands use the same aiogram filters as polling, including validation
of `@bot` mentions. Before current consent, arbitrary text is discarded by the
existing durable admission policy. Only normalized application input is encrypted;
no complete Telegram Update is persisted.

Admission commits/deduplicates the PostgreSQL event before publishing its UUID to
Redis. Duplicate requests can publish duplicate jobs; workers make them inert after
processing. A 5-second deadline bounds body read, dispatch, admission and publication.
No conversation, astrology or context generation occurs in the request.

## Responses

| Status | Body / meaning |
| --- | --- |
| 200 | `{"ok":true}` after admission/publication, or for unsupported events/deleting users |
| 200 | `{"method":"answerCallbackQuery","callback_query_id":"<incoming callback ID>"}` after accepted supported callback admission |
| 400 | `{"detail":"Invalid update"}` for malformed JSON/schema |
| 403 | `{"detail":"Forbidden"}` for missing, incorrect or duplicate secret headers |
| 413 | `{"detail":"Request too large"}` for an authenticated oversized body |
| 503 | `{"detail":"Temporarily unavailable"}` for unavailable lifecycle or admission/publication failure |
| 404 | `{"detail":"Not Found"}` when webhook ingress is disabled locally |

Admission/publication failures include `Retry-After: 1`. Every response uses the
gateway's generated `X-Request-ID`; caller-supplied IDs are not trusted. Callback
IDs are reflected only in the Telegram acknowledgement, not retained or logged.
The callback response requests acknowledgement without a separate API call; its
success cannot be observed by OriaEngine.

A failed/timed-out request may already have committed an event or published a job.
The provider can safely retry the same update, and PostgreSQL worker scans recover
the commit/publication gap independently. The synchronous Redis operation may
finish after request cancellation; any later publication still carries only that
same UUID. Account deletion keeps unlinked receipts, so accepted old updates cannot
recreate the deleted identity. Telegram delivery and downstream effects retain the
existing [at-least-once limits](../../docs/worker-queue.md).

## Configuration and compatibility

A nonempty webhook secret enables ingress and requires a bot token, encryption key
and current disclosure version. Production settings already require all service
URLs, HTTPS webhook base URL and secrets. Empty secret leaves the development HTTP
skeleton available without integrations. Enabled gateway readiness checks both
PostgreSQL and Redis connectivity; liveness remains independent.

Set/reset management appends `/telegram/webhook` to the configured HTTPS base URL
(including any prefix), registers only `message` and `callback_query`, and preserves
pending updates by default. Delete also preserves pending updates. Discarding
pending updates requires the explicit `--drop-pending-updates` CLI flag.
Gateway startup never registers or removes a webhook. Polling remains development-only.

This is the initial ingress contract. Additive Telegram fields remain compatible;
changes to authentication, canonical admission or response semantics require contract
and test updates. HTTPS termination and preserving the received secret header belong
to the deployment proxy. See [operator setup](../../docs/telegram-webhook.md).
