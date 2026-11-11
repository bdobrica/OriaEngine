# CH6 consumer verification — 2026-11-11

SecondContext implements conservative opt-in adaptive history with durable retry
selection and recent fallback. Its [operator guide](https://github.com/bdobrica/SecondContext/blob/main/docs/adaptive-history.md)
and [paired evaluation](https://github.com/bdobrica/SecondContext/blob/main/docs/evidence/conversation-history-ch6.md)
record the owning behavior. No Oria runtime adapter, policy, private deployment
configuration, version or image reference changed. Oria continues requesting recent.

## Consumer changes

Combined Compose accepts `SECOND_CONTEXT_HISTORY_ADAPTIVE_ENABLED=false`, passed
only to the SecondContext API. It does not turn on Oria capture, change its requested
mode or distribute Decisions credentials to the application. Tests verify provider
flag/secret isolation.

The real-gateway suite now includes a synthetic HTTP client explicitly requesting
adaptive: seed a horoscope, switch to a prepared compatibility question with a
standalone decision, then follow up with a recent-dependent decision. Captured
upstream prompts demonstrate omission, continuity, capability disablement and
rollback to recent without losing accepted conversation. The test also purges its
synthetic subject. Existing Oria handoff and observation tests remain unchanged in
meaning. This is actual provider HTTP behavior, not an Oria adaptive adapter claim.

Land the provider slice before this test slice: CI fetches the provider source.
The published v1 schema/fixtures are unchanged and synchronization passes.

## Verification

- Focused deployment contracts: **21 passed**.
- `SECOND_CONTEXT_SOURCE=/tmp/secondcontext-ch6 make test-history` with the installed
  tool wrapper: **27 passed**.
- Provider root verification and history/Decisions race checks passed; see its evidence.

- Root `make verify` passed using `UV='python3 /tmp/oria-och2-uv.py'`: Ruff format/
  lint, strict mypy (82 source files), 14 release checks, **611 unit** (two existing
  upstream warnings), **219 integration**, **392 contract**, **13 end-to-end**.
- Provider packaged-image checks passed, including adaptive capability enable/disable
  on schema 5, receipt recovery and erasure. Disposable task-owned resources were
  cleaned through scoped test scripts; no production maintenance was performed.

## Rollout decision

The 24-case live synthetic paired evaluation lost no required context and passed its
fact/topic checks, but estimated aggregate classifier-plus-generation cost rose
37.5% and median latency rose 399.5 ms. Two omitted long-history cases saved about
40–41% individually; these do not establish an overall benefit. Keep the default
recent until workload evidence supports a consumer opt-in.

Future consumer work must freeze the mode in each durable prepared request and
check advertised capability. On rollback, drain/abandon pending adaptive generation;
never rewrite an existing retry's header. Finalization, receipts and erasure remain
available. Publication, live rollout and private Telegram review remain open.
