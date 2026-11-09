# CH1 / OCH1 contract agreement — 2026-11-09

Scope: accepted ADRs and versioned wire contracts, authored provider JSON Schema,
synthetic fixtures, consumer snapshot/check tooling and PLAN/TODO sequencing.
No runtime route, auth allowlist, model call, migration, deployment or live policy
changed. SecondContext owns the schema; Oria tests its checked-in public snapshot.

Verified in Oria's existing Python 3.12 virtualenv:

- `python scripts/sync_history_contract.py --source /mnt/www/github/SecondContext --check`:
  schema and fixtures byte-identical to the provider working tree.
- `.venv/bin/python -m pytest tests/contract/test_history_schema.py -q`: 32 passed.
  Covers closed shapes, both acceptance variants/abandonment, exact receipt fields,
  versions, modes, input bounds, identifier syntax and source constraints. A
  wrong-subject shape deliberately still validates structurally: OCH2 must check
  identity against the request, and CH3 must enforce ownership in storage.
- `.venv/bin/python -m pytest tests/unit tests/contract/test_history_schema.py tests/contract/test_second_context.py tests/contract/test_knowledge.py -q`:
  718 passed, two existing Starlette/httpx/AnyIO deprecation warnings.
- `.venv/bin/python -m ruff check .`, `ruff format --check .`, and `mypy`:
  passed (245 formatted files, 77 checked source files).
- Both repository diffs passed `git diff --check`; contract/ADR local links and
  code fences were checked. Prior accepted ADRs and runtime files are unchanged.

The broad test run initially stalled at an existing mocked abuse-control async
thread test under the sandbox; a bounded reproduction timed out. That file passed
17/17 outside the sandbox, and the full 718-test command then passed there too.
No unrelated workaround was added.

`make verify` was not run: `uv` is unavailable on PATH; installed-environment
lint/type/unit/affected contract commands were used for this contract-only slice.
Docker integration/e2e, Go runtime gates, paid provider/cache evaluation, Telegram
and deployment checks were not run. These remain necessary in runtime/release
slices; schema agreement does not prove conversation continuity or erasure.
