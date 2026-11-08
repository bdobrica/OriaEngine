# Linked readings verification

Synthetic verification for slice 5: [behavior and limits](../linked-readings.md),
[additive calculation/context contract](../../contracts/astrology/linked-v1.md).
No live deployment or provider conversation is claimed.

## Aggregate gate

Ran the repository gate with the already installed environment:

```sh
make verify UV='/bin/sh /tmp/oria-existing-venv.sh'
```

The temporary wrapper implements `uv run` by executing the requested command with
the repository `.venv/bin` on PATH; `uv` is not installed on this host's PATH.
No verification lane was skipped. The gate exited zero:

| Check | Result |
| --- | --- |
| Ruff format/lint | Passed |
| Strict mypy | 77 source files passed |
| Release-matrix checks | 14 passed |
| Unit | 590 passed |
| Integration | 175 passed |
| Contract | 192 passed |
| End-to-end | 11 passed |

The unit lane reported two existing upstream TestClient deprecation warnings.
Integration used isolated Oria PostgreSQL/Redis test projects. Contract checks
built application/MCP images and exercised the real private HTTP MCP transport,
including both new calculation tools, alongside unchanged natal/transit cases.
Image deployment/development and end-to-end replay projects were isolated from
the live MVP and other projects on the shared host.

## Final focused checks

A final input-binding guard excludes an explicit own-birth clause from transient
other-chart inputs. After the aggregate run, verified the final source for that
guard and the completed reading path with:

```sh
.venv/bin/pytest tests/integration/test_linked_readings.py tests/unit/test_linked_readings.py tests/contract/test_linked_astrology.py -q
```

All **45** cases passed. Coverage includes:

- A birthday-only partner rating using actual supplied calculations, without
  own-profile edits, a transit request or raw birth fields in model facts.
- Self/partner/wedding charts and three comparisons, recalculated after an event
  correction; organization events retain an event convention instead of a human birth.
- Exact/approximate/sample precision, polar/missing-place houses, static aspect
  geometry, overlay direction and rejection of malformed/mismatched results.
- All twelve numbered house themes without treating the word “house” in those
  requests as a home/property mention.
- No-retention intent, fresh transient inputs, missing/unknown partners, a bare date
  continuing the reading, and an unresolved clock retained for later refinement.
- Own-birthday input never becoming the other chart; harmful requests never
  invoking the linked calculation path.
- Pending source delivery/erasure and the twenty-link response bound preventing
  unlinked remote generation; qualitative summaries retain canonical dependencies.
- Provider outage falling back to a current local reading, and canonical correction
  fencing old interpretation recall. Calculation failures retain transaction rollback.

Model replies and SecondContext HTTP lifecycle responses in these application
tests are synthetic. Numerical calculation uses the pinned real astronomy engine;
the separate MCP container checks verify the actual transport. SecondContext source
and its HTTP schema are unchanged by this slice; this is not a new owning-service
or live-provider retention audit.

Final format/lint/type checks, both schema generators' `--check` modes, and
`git diff --check` passed. Legacy natal/transit schemas, accepted ADRs, dependency
manifests/lockfile, image references and private deployment configuration are unchanged.
New schemas were generated from source. No migration is introduced.

Publication, live model/Telegram review, re-consent/configuration validation and
coordinated Oria-only rollout remain slice 6. Nothing was pushed, published or deployed.
