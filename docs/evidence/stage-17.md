# Stage 17 verification

Implementation date: 2026-10-03. Scope: deterministic profile inspection, existing
field editors, accurate privacy disclosure and final help text. See
[profile commands](../profile-commands.md).

## Checks

The first focused run passed 79 tests, covering profile inspection, consent changes,
the conversation worker, privacy filtering/disclosure length and Telegram routing.
Initial formatting reported four long strings; those were wrapped before tests.
Strict mypy passed against 53 source files.

The expanded focused integration run passed all 21 tests (126.80 seconds), including
place correction, repeated-clock-time selection, clearing that selection by choosing
unknown time, and queued inspection after withdrawal.

`make verify` completed successfully:

- Ruff formatting (131 files) and lint passed.
- Strict mypy passed (53 source files).
- Unit tests: 277 passed (36.13 seconds).
- Integration tests: 89 passed (404.58 seconds).
- Contract tests: 82 passed (46.00 seconds), including the MCP container test.
- Total: **448 passed**. Two existing Starlette/AnyIO deprecation warnings remain.

The task diff passed `git diff --check` excluding the pre-existing `LICENSE` change.
No source or test changes followed the aggregate gate; only evidence was finalized.

Coverage uses synthetic profiles and isolated PostgreSQL/Redis. Tests verify exact,
approximate and unknown-time display; normalized location details; owner isolation;
current/stale/withdrawn-consent chart status; inspection without starting collection;
separate confirmed and draft values; continued validity of edit buttons after inspection;
confirmation and recomputation; help before consent; unchanged consent on privacy display;
encrypted queued profile replies; reuse after send failure; and no model calls.

No live Telegram or AI-provider check is needed for these deterministic commands and
none was performed. No operator data, `.env`, sibling repository or live service was
modified. No dependency, migration, public wire schema or model prompt changed.

## Deployment and limits

Set `ORIA_POLICY_VERSION=2026-10-03.1` consistently for polling and workers, or bump
custom versions, then accept the new disclosure. The prior default is rejected to
prevent changed copy from silently inheriting previous acceptance. Preserve encryption keys.

Deletion remains Stage 18. Profile inspection after withdrawal is a local owner read;
it does not authorize collection, calculation or conversation. Replies retain the
existing encrypted queue lifetime, consent revision checks and Telegram delivery
limitations. Selecting a place controls its coordinates/timezone; these are not
independently editable free-text attributes. `/about` is unnecessary because `/help`
and `/privacy` already disclose AI identity and astrology limitations.

The pre-existing unrelated `LICENSE` line-ending change is excluded from this task.
