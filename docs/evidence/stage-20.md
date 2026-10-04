# Stage 20 verification

Scope: shared Redis sender limits, canonical per-user backlog caps, bounded text,
head-only publication/recovery with disposable UUID reservations, pre-parser MCP
response limits, retained SecondContext streaming limits and execution deadlines,
durable retry backoff with a final local failure reply, and an operator LLM switch.
No migration, dependency, generated schema or SecondContext owning-service change.
See [runtime behavior and limits](../abuse-controls.md).

## Verification

Focused unit/contract regression: 203 passed in 33.45 seconds. Focused queue,
conversation and deletion integration regression: 48 passed in 252.60 seconds,
using isolated PostgreSQL/Redis and synthetic providers/Telegram delivery.
The later focused lane passed 137 cases and exposed one legacy webhook assertion
that expected redundant broker jobs. It now asserts one reserved publication and
inert repeated worker delivery; its targeted rerun passed in 37.43 seconds.
Final `make verify` passed with exit status 0:

- Ruff formatting: 152 files unchanged; lint passed.
- Strict mypy: 58 source files passed.
- Unit: 351 passed in 38.15 seconds.
- Integration: 117 passed in 538.52 seconds.
- Contract: 88 passed in 58.39 seconds, including the rebuilt real MCP container.
- Total: 556 passing tests. Two existing Starlette/AnyIO deprecation warnings remain.

Relative documentation links resolve. The task diff passes `git diff --check`;
the unrelated pre-existing LICENSE line-ending changes are excluded. Final review
found no secret/runtime payload, generated-schema drift or unrelated source changes.
Only documentation was finalized after the aggregate gate.

## Coverage

- Concurrent Redis Lua admission across replicas, window expiry and key validation.
- Concurrent PostgreSQL backlog cap, receipt replay without budget consumption,
  completion freeing capacity and cap persistence after Redis flush.
- Excess text, non-BMP UTF-16 sizing and malformed surrogate rejection without
  identity or durable event creation; limit-store failure fails admission closed.
- A large legacy backlog contributes one recovery head; an unrelated sender still
  completes processing. Completed receipts are ineligible for publication.
- Repeated publication of the same UUID creates one broker message; failed enqueue
  releases its reservation and completed claimed work releases coordination.
- Existing retry deadlines, attempt limits and whole-operation timeouts; final typed
  downstream failure sends a fixed notice after rolling back partial domain mutation.
- Disabled generation/memory ingestion without provider or session calls; profile
  inspection and privacy commands remain available. Deletion preserves its provider
  purge path and removes only its exact sender abuse keys.
- Webhook 200 acknowledgement with optional bounded message/callback feedback,
  polling rejection without an endless retry, and unchanged authentication errors.
- MCP JSON/SSE streamed byte boundary, compression refusal, cancellation and stream
  cleanup; SecondContext exact decoded-byte boundary and chunked overflow cleanup.
- Real HTTP MCP compatibility through the aggregate container contract test;
  generated natal/transit JSON schemas remain unchanged.

## Operational limits

No public HTTPS/Telegram load test or live paid-model call was made. Tests use
isolated temporary services, not the operator's running database or SecondContext.
The switch applies after all worker processes restart; running calls and committed
replies may finish. Per-user controls are not global cost quotas or multi-account
abuse protection. Rejected updates have no durable receipt and notice delivery is
best effort. Publication reservations expire after crashes; PostgreSQL owns recovery.
No live bot registration or deployment configuration was changed.
