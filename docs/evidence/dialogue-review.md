# Authored dialogue review — 2026-11-06

## Change

Preserved the thirteen fictional sketches unchanged under `docs/dialogue/examples/`.
The [review guide](../dialogue/README.md) analyzes their conversational patterns,
maps reading insertion points for each sketch and adds a worked insertion using
synthetic calculated transit facts. The originals have no calculated charts.

`AGENTS.md`, the plan, README and consent/persona references now explicitly place
the thorough disclosure in the adult consent flow and favor natural dialogue
afterwards. Prompt versions are `oria-policy-3`, `oria-methodology-3` and
`oria-voice-2`. The model is no longer instructed to emit a canned professional-support
reminder. Voice guidance emphasizes direct readings, accepting corrections, optional
questions, user-selected pace and room for enjoyment or an unresolved ending.

The tone corpus adds a supported review turn for each sketch and the synthetic
reading. The optional evaluator can supply transit facts for that additional case.
Fixtures and source scenes are review artifacts, never production instructions.
No consent copy/version, wire contract, schema, migration or dependency changed.

## Verification

Focused persona, SecondContext contract and policy checks passed: 129 tests.
The expanded unit suite passed all 447 tests; database integration passed all 122.
New checks validate that the curated review turns reach supported routes, their
reference replies survive current guards and the worked insertion matches an engine
calculation: transiting Jupiter trine natal Sun at 2026-10-02 12:00 UTC, applying,
orb approximately 3.02 degrees. Relative documentation link targets were checked.

The complete root gate passed: Ruff formatting/lint, strict mypy, 14 release tests,
447 unit tests, 122 integration tests, 126 contract tests and 11 Telegram replays.
The command was `make verify UV='/bin/sh /tmp/oria-existing-venv.sh'`: because `uv`
was absent from PATH, that temporary launcher forwarded `run <command>` to the
already installed `.venv` binaries. No dependencies were installed or changed.
An initial sandboxed attempt stalled in an existing asynchronous unit test and was
interrupted; the final gate ran outside the sandbox and completed successfully.
Docker checks used isolated test projects. Two upstream TestClient deprecation
warnings were non-fatal. Final diff and relative documentation links were reviewed.

## Limits

No live model, paid provider, real Telegram conversation or live deployment check was run.
Authored replies and deterministic tests do not establish live conversational quality.
The evaluator reviews isolated turns; multi-turn model review remains outstanding.
Existing narrative/date-routing false positives, lexical guard false positives and
transit/history continuity gaps are documented in the review guide and TODO.
