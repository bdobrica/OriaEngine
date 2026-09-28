# Stage 13 verification — 2026-09-28

Scope: additive transit MCP v1, deterministic active routing, constrained fact
summaries, and optional typed transit facts at the existing context adapter boundary.
Behavior and compatibility are documented in [transits and routing](../transits-and-routing.md).

## Focused checks

- 72 focused router, MCP client, natal and transit contract checks passed.
- 10 PostgreSQL active-flow and derived-profile checks passed.
- The expanded 90-test selection passed its assertions, but its new queue test
  initially failed teardown because the existing fixture did not clear confirmed
  birth profiles. Adding that related cleanup made the focused queue test pass.
- Strict mypy passed for 46 source files; Ruff formatting and lint passed.

Numerical checks compare transit longitude/speed against the existing independent
C `swetest` fixture, at the documented `1e-6` tolerance. Same-body returns prove
that natal references remain fixed. A one-minute finite difference at a second
target verifies applying/separating signs, while existing analytical tests cover
wraparound, orb boundaries, stations and exactness. No time-to-exact method is
validated or exposed; the contract explicitly returns unavailable.

Privacy and workflow checks cover consent gating, foreign-user isolation,
profile-edit gating, active routing without profile decryption, unknown and
approximate birth time, no unnecessary transit calls, ambiguous date clarification,
generic failure recovery, timestamp/accuracy response mismatches, cancellation,
facts-only context instructions and queue delivery retries without recalculation.

## Aggregate gate

`make verify` completed successfully:

- Ruff formatting and lint; strict mypy over 46 source files;
- 209 unit tests passed;
- 68 integration tests passed against isolated PostgreSQL/Redis;
- 75 contract tests passed, including the rebuilt MCP container, real HTTP
  known/unknown-time natal and transit calls, and generated-schema drift checks.

Total: **352 tests passed**. The unit suite emitted two existing Starlette/AnyIO
deprecation warnings. No code changed after this successful gate.

## Verification boundary

Tests use synthetic identities/profile inputs, isolated PostgreSQL/Redis and
mocked Telegram/SecondContext responses. The MCP container check uses the real
private-network HTTP transport and engine. No live Telegram conversation,
OpenAI call, operator database migration or public deployment was performed.
No new schema migration or dependency is introduced. Natal v1 schema and fixture
remain unchanged. Existing local LICENSE line-ending changes and the untracked
virtual-environment link are outside this change.
