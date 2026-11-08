# Conversation-memory release evidence

Date: 2026-11-08. Source verification complete; publication and live rollout pending.

The candidate uses Oria application/MCP image version `0.2.0`, SecondContext gateway
`0.2.1` and disclosure `2026-11-08.5`. Versioned consent covers the expanded
learning/retention lifecycle, birthday samples, house themes and symbolic ratings.
No ordinary reading gains a recurring general disclaimer.

## Source verification

- Focused consent/startup checks: 106 passed. After the final policy-version guard
  and disclosure checks, the full unit suite passed 592 tests with two existing
  upstream TestClient deprecation warnings.
- Synthetic Telegram/SecondContext HTTP replays passed 13 tests against real
  isolated PostgreSQL/Redis and MCP. New fixtures cover partner birth, wedding,
  house/phone purchase, pet adoption, job change, business/non-profit foundation
  and parents' divorce, CRUD, opt-out, withdrawal and versioned re-consent.
- SecondContext's root `make verify` passed using the installed Go toolchain,
  including mandatory dependency-backed tests without skipped cases. Its packaging
  check passed against fresh isolated storage, checking migration `000004`, new
  projection tables, scoped purge, repeat migration and startup blocked by dirty schema.
  Release fixes invoke its integration script through Bash and update the old
  packaging assertion from schema 3 to 4. No service authority or storage boundary changes.
- Oria's final `make verify` passed: formatting/lint, strict mypy over 77 source
  files, 14 release-selection checks, 592 unit, 176 integration, 193 contract and
  13 E2E tests. No lane was skipped. Both contract generators passed `--check`;
  existing natal/transit schemas and other published wire shapes are unchanged.
  The release-check script also passed explicit strict mypy with source imports.
- SecondContext `0.2.1` source `683fa7e83512afa0172e79f14f38c31a2c61d47a`
  passed both [CI jobs](https://github.com/bdobrica/SecondContext/actions/runs/42515453500)
  and [publication](https://github.com/bdobrica/SecondContext/actions/runs/42515453537).
- Application/MCP publication and live rollout remain pending.

## Live review boundary

Tests above use synthetic model replies. They establish deterministic routing,
storage and transport behavior, not real provider quality or Telegram delivery.
The [release checklist](../conversation-memory-release.md) provides the separate
synthetic-subject live check and private Telegram review. No live data, credentials,
generated replies or backup contents belong in this record. The broader Stage 25
MVP checklist remains separate.
