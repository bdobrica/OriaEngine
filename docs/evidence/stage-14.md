# Stage 14 verification — 2026-09-28

Scope: separate product policy, astrology methodology and Oria voice modules;
deterministic assembly in the existing SecondContext adapter; authored tone examples.
See [prompt behavior and boundaries](../persona-prompts.md).

## Focused checks

`uv run pytest tests/unit/test_persona.py tests/contract/test_second_context.py`:
**46 tests passed**. The initial run had one source-file assertion fail because it
depended on the current working directory. That redundant assertion was removed;
the behavioral override rejection checks remain, and the focused suite then passed.

Tests cover policy/methodology preservation when voice is removed or replaced,
assembly order, unchanged typed natal/transit data for all three accuracy states,
no raw birth/identity fields, request/input separation and consistent assembly
across the six authored tone scenarios. Existing adapter scope, retries, deadlines,
purge and fact-channel contract tests also pass.

The injection-shaped input/memory case checks transport separation and explicitly
shows that the adapter returns an untrusted draft. It is not a safety classifier
or proof that a model resisted injection.

## Aggregate gate

`make verify` completed successfully:

- Ruff formatting and lint; strict mypy over 51 source files;
- 216 unit tests passed;
- 68 integration tests passed against isolated PostgreSQL/Redis;
- 82 contract tests passed, including the rebuilt MCP container and generated-schema
  drift checks.

Total: **366 tests passed**. The unit suite emitted two existing Starlette/AnyIO
deprecation warnings. No code changed after the successful gate. Final staged diff
review found no generated-file drift or unintended wire/schema changes.

## Review boundary

The six synthetic conversation references were reviewed for calm, concise tone,
separation of facts/interpretation/reflection, uncertainty, user agency, transparent
AI identity and non-identifying follow-ups. They are authored examples, not model
outputs or numerical engine fixtures. No live-provider tone/compliance evaluation
was run; Stage 16 carries that explicit follow-up.

No live Telegram/OpenAI calls, operator migrations, public deployment, new dependency,
wire schema change, sibling repository edit or consent-policy activation is involved.
The worker remains on deterministic fact replies. Stage 15 owns policy enforcement;
Stage 16 owns generation/validation wiring. Existing LICENSE line-ending changes
and the untracked virtual-environment link are outside this change.
