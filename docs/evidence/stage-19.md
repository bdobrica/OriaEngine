# Stage 19 verification

Implementation/verification date: 2026-10-04. Scope: authenticated HTTP Telegram
ingress, existing durable admission/queue integration, explicit webhook management
and proxy/TLS instructions. See [webhook setup](../telegram-webhook.md) and the
[ingress v1 contract](../../contracts/telegram/webhook-v1.md).

## Checks

- Initial focused unit regression run: **134 passed** (21.63 seconds), covering
  webhook, HTTP skeleton, Telegram polling/normalization and configuration.
- Focused integration run: **20 passed** (111.71 seconds), covering webhook and
  existing queue behavior with isolated PostgreSQL/Redis and actual Dramatiq messages.
- Initial production ingress contract run: **3 passed** (13.51 seconds).
- Formatter/lint and strict mypy passed during development (56 source files).
- `make help` and dry-run `make -n webhook-set webhook-delete webhook-reset` passed.

- Final focused webhook unit/contract run: **54 passed** (14.37 seconds), including
  the added cancellation and diagnostic privacy checks.
- Repository-local links in the affected Markdown documents resolve.

`make verify` completed successfully:

- Ruff formatting (144 files) and lint passed.
- Strict mypy passed (56 source files).
- Unit tests: **330 passed** (35.69 seconds).
- Integration tests: **105 passed** (478.15 seconds).
- Contract tests: **85 passed** (59.51 seconds), including the real MCP container test.
- Total: **520 passed**. Two existing Starlette/AnyIO deprecation warnings remain.

The final task/staged diffs passed `git diff --check`. No source or test changes
followed the aggregate gate; only this evidence was finalized.

## Coverage and limits

Synthetic tests cover secret validation before parsing, missing/wrong/duplicate
headers, malformed bodies, authenticated size limits including chunked input,
unsupported chat/update types, command parity and bot mentions, private callback
ownership, callback acknowledgement through the HTTP response, bounded admission
failure, cancellation propagation, payload-free diagnostics, readiness, lifecycle
cleanup and management parameters/failure cleanup. The management tests preserve
pending updates by default and exercise the explicit discard option only against
mocked APIs.

Real PostgreSQL/Redis integration covers concurrent provider retries producing one
event/identity/domain action, actual UUID-only broker messages, completed event
replay, database failure/retry, durable recovery eligibility after enqueue failure,
pre-consent text/metadata minimization, rejection without identity creation and
dependency readiness. Existing queue, deletion and privacy suites remain regression
coverage for owner fencing, ordering, domain idempotency and safe old receipts.

The production HTTP contract lane uses mocked admission/publication and validates
response shapes, additive Telegram fields, unsupported updates and disabled API
docs. It does not prove external HTTPS routing or bot credentials.

No live Telegram registration/deletion, Telegram exchange, TLS deployment,
SecondContext request, OpenAI call, operator migration or real account deletion was
performed. Nginx is unavailable in the execution environment, so the proxy example
was not syntax-checked with `nginx -t` or deployed. User `.env`, services, data and
the sibling repository were not modified.

No migration, dependency, consent disclosure, astrology or SecondContext wire
change is introduced. The new ingress v1 contract documents the initial public
HTTP boundary. A timed-out publication can finish later; duplicate UUID jobs are
safe. Worker remote effects/Telegram replies retain their at-least-once limits.
The webhook callback acknowledgement result cannot be observed by the gateway.

## Activation

Prepare the public HTTPS reverse proxy, configure base URL/secret privately and
start the gateway and workers with the existing migrated storage and stable key.
Stop polling for that bot, then explicitly run `make webhook-set` and perform a
synthetic live check. Set/delete/reset Make targets preserve Telegram pending
updates. Automatic startup does not change webhook registration.

The pre-existing unrelated `LICENSE` line-ending change is excluded from this task.
