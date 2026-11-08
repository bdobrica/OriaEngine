# Canonical private-memory verification

Verified on 2026-11-08. This is source/test evidence for slice 3, not a deployment,
live-provider check or acceptance of SecondContext's proposed knowledge lifecycle.
See [implemented behavior and limits](../private-memory.md).

## Implemented scope

- Migration `0011`: encrypted canonical event/entity payloads, same-owner dependency
  edges, revision/source provenance, terminal deletion fences, mutation receipts and
  encrypted temporary focus/selection. Birth profiles gain a monotonic revision;
  own-birth events are virtual references, without duplicated birth fields.
- Bounded English learning and conversational lookup, correction and local removal;
  aliases, former relationship labels, explicit place labels, partial/approximate
  precision, unknown dates/times and saved date anchors. Multiple occurrences and
  unclear entity identities ask for selection. Opt-out and non-assertions do not
  become canonical facts. Explicit reading requests can continue after a local save.
- Original ingress clock, timezone source, selected revision and logical operation
  survive date/record clarification, restart and retries. Owner locks serialize
  mutations with withdrawal and deletion. Committed receipts are composed locally,
  not supplied by model output. Provider failure rolls back an unacknowledged save.
- Selective erasure removes affected local payloads, links/provenance and suspended
  state. Replay cannot restore a forgotten UUID. Account deletion covers all new
  tables and retains the existing validated remote subject-purge dependency.
- Consent `2026-11-08.3`, policy `oria-policy-6`, command/help and repository references
  describe this storage. Existing users must accept the new disclosure before
  learning. Read/remove controls remain available after withdrawal. No recurring
  general disclaimer was added to ordinary readings.

## Checks actually run

The documented Make targets used the existing installed `.venv` through a temporary
`UV` runner, because `uv` is unavailable on PATH:

```sh
make verify UV='/bin/sh /tmp/oria-existing-venv.sh'
make test-unit test-integration UV='/bin/sh /tmp/oria-existing-venv.sh'
```

The aggregate gate passed: formatting/lint, strict typing, 14 release checks,
555 unit tests, 157 integration tests, 164 contract tests and 11 end-to-end replays.
Final review tightened whole-word record selection and added its regression;
the complete unit/integration rerun then passed **556 / 157** tests. A final focused
integration regression passed after clearing suspended memory selection on entry
to birth-profile editing. These are separate runs, not one aggregate count.
Final formatting/lint checked 219 Python files; mypy checked 70 source files.

Both schema generators passed `--check`:

```sh
.venv/bin/python scripts/generate_knowledge_schema.py --check
.venv/bin/python scripts/generate_astrology_schema.py --check
```

The new memory tests cover encryption/AAD and revision tampering, wrong-owner reads,
database-enforced same-owner edges, canonical recall after restart, deduplication,
name/relationship corrections, partial dates, place updates, approximation,
ambiguous occurrences/entities, original clock/zone/operation preservation across
successive questions, expired/stale consent state, opt-out, provider rollback,
withdrawal serialization and suspended-selection cleanup. Existing worker tests
exercise encrypted reply reuse, queued read/removal after withdrawal, full account
erasure and remote purge failure/retry. Migration tests cover empty/repeated upgrade,
metadata drift, downgrade and re-upgrade. Container contracts include development
and published-image deployment workflows in isolated test projects.

Tests use synthetic records, mocked Telegram/provider calls and unique Oria Compose
projects. No live Telegram/OpenAI call, MVP migration, image publication, push or
rollout was performed. Private deployment configuration, accepted ADRs, dependencies
and published astrology/knowledge JSON schemas were unchanged.

## Limits

This is a bounded application extractor and local canonical store, not general
language understanding, semantic salience or a new calculation service. Unsupported
forms may need rephrasing. Local removal does not claim erasure of independent
conversation/provider/Telegram/backup copies. Remote event projection ingestion
stays disabled until slice 4's owning-service authorization, revision fencing,
selective erasure and purge coverage are accepted and verified.
