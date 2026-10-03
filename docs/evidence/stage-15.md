# Stage 15 verification

Date: 2026-10-03.

Implemented the application-owned English solicitation/high-stakes guard, shared
active-routing categories, fixed replacement replies and central onboarding field
projection. No dependency, database migration or published wire/schema change.
The low-level context adapter still returns drafts; the consent-fenced application
service now validates them. No external conversation flow was enabled.

## Focused checks

`uv run pytest tests/unit/test_policy.py tests/unit/test_active.py
tests/contract/test_second_context.py tests/integration/test_context.py` initially
reported 114 passes and one failure: “legal name” incorrectly matched the legal
advice category. Excluding that phrase from the high-stakes keyword fixed the
overlap. The focused policy/router rerun passed all 73 tests. A final service
pass-through test and revoked-consent/high-stakes assertion were then added for
the aggregate gate.

The synthetic corpus covers hostile requests for email/phone, policy overrides,
model output following malicious retrieved instructions, diagnosis, guaranteed
investment, death, pregnancy, accidents, criminality, financial ruin, relationship
failure and legal outcomes. Additional tests cover prohibited field categories,
Unicode normalization, negation/quotation bypass attempts, allowed reflection and
uncertainty, strict profile fields and the read-only gateway surface.

## Aggregate gate

`make verify` passed (exit 0):

- Ruff formatting (122 files) and lint passed.
- Strict mypy passed for 52 source files.
- 259 unit tests passed, including 43 policy tests.
- 68 integration tests passed against isolated PostgreSQL/Redis.
- 82 contract tests passed, including the MCP container and schema checks.

Total: **409 tests**. Two existing Starlette/AnyIO deprecation warnings remain.
The task diff passed `git diff --check` with the unrelated `LICENSE` excluded.

## Scope and limitations

Tests simulate compromised model output; they do not establish live-model prompt
injection resistance or tone quality. No live Telegram, SecondContext or LLM call
was made, and no provider key was required. Isolated test services are separate
from operator data. The guard is lexical and English-oriented, with conservative
false positives and incomplete paraphrase/obfuscation coverage. It does not remove
blocked drafts already retained upstream or filter volunteered inbound PII.
Stage 16 owns worker integration and disclosure before external transcript storage.

The pre-existing `LICENSE` line-ending change is excluded from this implementation.
