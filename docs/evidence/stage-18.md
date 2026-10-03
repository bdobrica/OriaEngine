# Stage 18 verification

Implementation/verification dates: 2026-10-03–04. Scope: explicit account-deletion confirmation,
durable cleanup and recovery across OriaEngine, SecondContext and Redis, identity
removal, replay protection and final notification. See [deletion](../deletion.md).

## Checks

Migration `0008` was generated with Alembic autogeneration against an isolated
database upgraded to the previous head, then reviewed. Its custom development
downgrade removes unlinked receipts before restoring the non-null owner constraint.
No operator database migration was run.

- First focused run: **61 passed** (116.95 seconds), covering deletion, migration
  upgrade/repeat/downgrade/metadata, Telegram routing and existing profile commands.
- Expanded deletion/queue/conversation regression run: **38 passed** (202.34 seconds).
- Strict mypy passed against 54 source files during both focused runs.

`make verify` completed successfully:

- Ruff formatting (136 files) and lint passed.
- Strict mypy passed (54 source files).
- Unit tests: **279 passed** (42.37 seconds).
- Integration tests: **99 passed** (502.73 seconds).
- Contract tests: **82 passed** (50.59 seconds), including the real MCP container test.
- Total: **460 passed**. Two existing Starlette/AnyIO deprecation warnings remain.

The reviewed task diff passed `git diff --check`; the staged diff excludes `LICENSE`.
No source or test changes followed the aggregate gate; only this evidence was finalized.

## Coverage and limits

Synthetic tests use isolated real PostgreSQL and Redis, mocked Telegram sends and
the stateful versioned SecondContext HTTP contract stub. They cover local profile,
draft, chart, consent and session erasure; remote memory/session removal and refusal
of late responses; owner isolation; consent-independent confirmation; cancellation;
expiry; stale/cross-user buttons; duplicate confirmation; queued work; concurrent
deletion workers; waiting for in-flight owner operations; context and Redis failures;
durable backoff; process restart and ambiguous remote acknowledgement; targeted Redis
key removal; final-message retry/expiry without account recreation; inert old updates;
and a fresh UUID/consent flow on return. Development downgrade after real deletion
is also covered by the aggregate run.

The adapter's existing strict purge-response tests remain part of the contract lane.
Upstream PostgreSQL/Qdrant purge implementation evidence is in [Stage 12](stage-12.md).
This stage did not run a live SecondContext deployment purge, Telegram exchange or
OpenAI call. The HTTP stub does not prove a particular deployment's purge capability.
No operator data, `.env`, sibling repository or live service was modified.

No new dependency, public wire contract or model prompt was introduced. Deletion
retains minimal subject/job markers and unlinked update receipts; backup, retired
index, AI-provider and Telegram retention are separate. Final Telegram delivery is
at least once and retries for 24 hours after cleanup; worker scans erase expired
routing ciphertext. Active purge failures remain blocked and retry without an
attempt cap, requiring operator repair when authentication/capabilities are missing.

## Deployment

Run `make migrate`, configure `ORIA_POLICY_VERSION=2026-10-03.2` consistently for
polling and workers (bump custom versions), restart them, and accept the new disclosure
for chat. Deletion itself works without current consent. Configure authenticated
SecondContext subject purge as documented in [adapter setup](../second-context.md),
preserving the namespace used for existing data. Keep profile encryption keys
available until pending notifications have been delivered or expired.

The pre-existing unrelated `LICENSE` line-ending change is excluded from this task.
