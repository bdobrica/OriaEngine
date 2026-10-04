# Stage 24 verification evidence

Date: 2026-10-04. Scope: documentation reconciliation and developer onboarding.

## Documentation changes

- README now gives the credential-free bootstrap/test path and the shortest
  container-worker/polling demo, with prerequisites and durable guide links.
- Configuration reference covers all typed settings and distinguishes Compose-only
  variables, URL precedence, development overrides and authenticated deletion.
  `.env.example` retains safe defaults and adds matching explanations.
- Architecture reference records implemented component ownership and message flow
  with Mermaid. Known limitations cover calculation/input coverage, lexical policy
  guards, remote retention, ambiguous retries, keys and outstanding operator checks.
- Existing guides retain BotFather, polling/webhook setup, SecondContext, MCP,
  migrations, test lanes, privacy and deletion instructions. Stale future-stage
  wording has been reconciled with the implemented worker and development stack.
- `make help` includes targets containing digits, so `test-e2e` is discoverable.
- PLAN/TODO point next to Stage 25 without declaring the MVP release gate complete.

## Validation

Read-only documentation checks passed: 255 relative links/anchors across README,
PLAN, TODO and top-level guides resolve; documented Make targets exist; all 17
typed settings appear in the example/reference. The example parses successfully
and all typed values match `Settings` defaults. All 31 documented targets appear
in `make help`. `make -n dev down run webhook-set test-e2e` matches the described
commands. The key-generation snippet was parsed without generating or printing a key.

A fresh temporary source export of the previous commit plus this change was used
for the README workflow. No `.env`, existing virtual environment, operator files or
unrelated `LICENSE` edits were copied. `make bootstrap` created a new virtual
environment with Python 3.13.5 and frozen dependencies; existing package/image
caches were available. This was not an uncached network-install test or a live
`git clone` of the unpublished change. Focused `make test-unit`: **380 passed**,
17.10 seconds.

Full `make verify` passed in that fresh source export (exit 0):

| Gate | Result |
| --- | --- |
| Ruff format/lint | 175 files passed format check; lint passed |
| Strict mypy | 60 source files passed |
| Unit | 380 passed, 14.31 seconds |
| Integration | 120 passed, 143.09 seconds |
| Contract | 93 passed, 131.94 seconds |
| E2E | 11 passed, 60.33 seconds |

Total: **604 tests passed**. Two existing Starlette/AnyIO unit deprecation warnings
occurred. uv used its existing cache with a harmless cross-filesystem hardlink
fallback. Container tests and replays used generated credentials and their own
dependency projects. No local application stack was started with operator settings.

Final documentation link/command/configuration and whitespace checks passed.
The final diff was reviewed for unrelated changes, accidental secrets,
generated-file drift and unintended contract changes.

## Scope limits

This pass changes documentation, example comments and Make help output only.
No application behavior, workflow recipe, dependency, migration, generated schema
or published wire contract changes.
No live Telegram/LLM, upstream SecondContext deployment, public TLS, provider
retention, backup/restore or GitHub Actions run is claimed. Those checks remain
in Stage 25. No operator `.env`, database, external service or real credential was
modified. Pre-existing `LICENSE` line-ending drift is excluded.
