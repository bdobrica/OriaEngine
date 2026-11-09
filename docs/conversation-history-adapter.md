# Conversation history adapter

OCH2 implements the [accepted consumer contract](../contracts/second-context/conversation-history-v1.md)
under [ADR 0003](adr/0003-accepted-conversation-history.md). It adds no deployment
switch or worker behavior: ordinary `respond()` still uses the legacy Responses
path. OCH3 must implement durable acceptance, consent/disclosure and delivery before
the worker calls the new methods. No provider database or internal types are used.

## Adapter boundary

`SecondContextProvider` exposes:

- `history_capabilities(user_id, refresh=False)`: authenticated POST discovery,
  closed typed result and exact subject validation. Requires the two generation
  endpoints, recent/off, explicit/generated, all finalization actions, linked-session
  coverage and the contract's input/reply/TTL limits. Additional unknown fields,
  partial capabilities and old routes fail. Adaptive advertisement is understood
  but the Oria adapter still sends only recent/explicit.
- `prepare_history_turn(scope, request, turn_id=...)`: pure construction of a
  redacted, immutable `PreparedHistoryTurn` from prepared active input, current
  instructions/facts, goal and bounded source references. The caller supplies the
  persisted ingress-event UUID; no new turn/session ID is allocated. Serialize and
  encrypt this DTO before the first attempt; restore it for retries instead of
  recalculating time, facts or source revisions. Arbitrary metadata, model settings,
  prior dialogue, tools and mode overrides are not accepted.
- `respond_history(scope, prepared)`: verifies scope and capability, sends the fixed
  recent/explicit headers plus the matching session metadata to `/v1/responses`,
  validates the existing response body and exact Contract/Session/Turn/Snapshot
  echoes, then returns a scoped `HistoryDraft`. A draft is never an acceptance
  receipt. The result remains subject to Oria's output validation/replacement.
- `finalize_history(scope, request)`: sends a closed `AcceptGenerated`, `AcceptLocal`
  or `Abandon` DTO. Requires exact owner/session/turn/action, response ID where
  applicable, status, safe positive sequence and linked coverage in the receipt.
  It never calls capability discovery: existing finalization/abandonment recovery
  must remain possible when new capture is unavailable. New local capture needs
  capability, eligibility, consent and source checks in OCH3; a valid DTO does not
  establish those checks. This method is intended for post-commit work only.

Both service namespace and existing subject-bound bearer modes work. Managed calls
require a configured bearer even if legacy development is unauthenticated. Body
subject and scoped header are derived from Oria identity/configuration, never
channel IDs or model output. Prepared requests with a different owner/session or
namespace are rejected before HTTP. A provider instance represents one immutable
configuration epoch; recreate it when credentials/base URL/namespace change.

## Bounds and recovery

Each HTTP call retains the 20-second total deadline, at most three connection
establishment attempts and at most three seconds for connection establishment.
No redirects or environment proxies. Capability and receipt responses are limited
to 16 KiB decoded; generation remains limited to 256 KiB. Finalize requests are
bounded to 128 KiB. Duplicate JSON keys, invalid Unicode, duplicate/missing managed
headers and unsafe numeric sequences fail closed. No upstream body or error message
is included in adapter exceptions or diagnostics.

Successful capabilities are cached per subject for 60 seconds, at most 128 entries,
only within this provider instance. `refresh=True` forces rediscovery, including
failure invalidation; `clear_history_capabilities()` invalidates all cached results
after a deployment change. Generation/finalization failures invalidate that subject's
entry. Cache entries store capability metadata, never dialogue; cached readiness
does not override provider fences or authorize application work.

`HistoryUnsupported` identifies missing auth or failed capability negotiation.
It never triggers legacy fallback. `HistoryFailure` retains only a matched,
allowlisted contract code/status; only `turn_in_progress`, `turn_pending` and
`history_unavailable` are marked retryable. Unknown/malformed errors and transport
failures remain generic `ContextUnavailable`; ambiguous failures do not prove that
the write failed. HTTP failures and ambiguous read/write/deadline failures are not
automatically retried. OCH3 owns the bounded retry policy and persisted exact body,
including receipt comparison across retries and terminal/uncertain outcomes.

## Remaining integration

OCH3 must atomically persist the validated reply and encrypted finalization work,
recheck consent/source revisions post-commit, finalize before independent Telegram
delivery, and resolve earlier pending work before generating another turn. Privacy
and erasure bypass that barrier. It must also implement the local-exchange allowlist,
cancellation, expiry and fresh-consent disclosure. No schema or policy version is
changed here. OCH4 proves cross-service replay and recovery; OCH5 coordinates rollout.

See [verification evidence](evidence/conversation-history-adapter.md).
