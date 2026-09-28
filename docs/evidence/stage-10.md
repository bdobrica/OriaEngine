# Stage 10 verification — 2026-09-28

Implemented derived natal persistence, consent-checked activation, cache versioning,
retry, edits and the application MCP adapter. No public wire schema changed.
Migration `0005` was generated with Alembic against isolated PostgreSQL and reviewed.

Validation on Python 3.13.5:

- Focused adapter tests: 4 passed.
- Focused database lifecycle tests after fixing write ordering: 6 passed.
- `make verify`: formatting, lint and strict mypy passed; 164 unit tests,
  47 integration tests and 26 schema/calculation contract tests passed.
- That aggregate run failed its final container test: the polling override could
  not publish a port from an internal-only Docker network. The default private
  transport passed. Added a bridge network only in the explicit polling override.
- `make mcp-test` after that fix: 1 passed, covering the real application adapter
  over private HTTP MCP and loopback HTTP MCP. Total: 238 passing tests across the
  aggregate run and focused retry; the aggregate command was not rerun afterward.
- Diff whitespace checks passed excluding the pre-existing LICENSE change.

Coverage includes migration upgrade/repeat/downgrade/metadata drift, exact,
approximate and unknown-time confirmation, restart/retry, failed refresh retaining
previous state, source edits, engine/timezone invalidation, user isolation, consent
withdrawal, serialized concurrent calculation and legacy overlap clarification.
Only synthetic data and isolated test infrastructure were used. No developer
migration, live Telegram check, model call or public deployment was performed.
