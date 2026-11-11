# CH4/CH5 consumer compatibility — 2026-11-11

SecondContext now implements optional context-dependence observation and cache
measurement. Its [operator guide](https://github.com/bdobrica/SecondContext/blob/main/docs/decisions-observation.md)
and [implementation/live evaluation evidence](https://github.com/bdobrica/SecondContext/blob/main/docs/evidence/conversation-history-ch45.md)
record the owning implementation. Observation preserves recent-history generation;
CH6 adaptive selection remains gated. This change does not publish images, enable
production observation, change the policy version, or change Oria's runtime input
preparation/acceptance/delivery behavior.

## Oria changes

The combined Compose file accepts optional `SECOND_CONTEXT_DECISIONS_*` settings,
including a separate API key and random cache secret, and optional generation cost
rates. Only the SecondContext API container receives them. Observation defaults off.
The application, astrology MCP, storage and migration containers receive neither
these credentials nor classifier configuration. A compatible published provider
image and existing consent/release gates are required before enablement.

Land the owning provider slice before this consumer test slice so CI checks out
a gateway containing the observer. Public history wire definitions are unchanged.

The existing private-reading handoff regression now runs with observation disabled
and enabled against the real gateway. A synthetic classifier returns a confident
standalone prediction, while assertions prove that generation retains recent
history. The horoscope → compatibility/private clarification → plain-English
follow-up → new topic sequence supplies the current reading cue and calculated
facts to both upstream requests, excludes the raw private answer/save receipt from both,
and clears current linked facts when the topic changes. No real private transcript
or account information is retained in fixtures or this evidence.

## Verification

- Focused deployment suite: **21 passed**, including credential/rate isolation.
- Real gateway history suite: **26 passed**, including both observation variants.
- Root verification components: Ruff format/lint, strict mypy (82 source files),
  **14 release-selection checks**, **611 unit**, **219 integration**,
  **392 contract**, **13 end-to-end** checks passed. Two existing upstream unit
  warnings remain. Local commands used the established installed-tool wrapper
  `make verify UV='python3 /tmp/oria-och2-uv.py'`.
- The first aggregate run reached contract checks but two Docker-dependent cases
  failed because the host's default network address pool was exhausted. After
  inspecting ownership and proving they had no attached containers, four explicitly
  identified empty disposable Oria test networks were removed (three preexisting,
  one from the failed fixture). `make test-contract test-e2e` then passed. Passing
  unit/integration checks were not needlessly repeated. No host-wide pruning,
  live-resource deletion or unrelated-project cleanup occurred.
- SecondContext's full verification, history/Decisions race tests, packaged-image
  check and explicit live synthetic evaluation are recorded by the owning repository.
  The final observer budget-label refinement is covered by its own integration test.

Older disposable Oria astrology test containers were also observed on the shared
host. Their cleanup/fixture behavior is a separate existing maintenance issue;
this implementation does not modify that behavior or remove those containers.

Production remains Oria **0.2.3**, SecondContext **0.2.2**, MCP **0.2.1** with the
existing image digests and disclosure. Publication/rollout and the participating
user's private Telegram retest remain separate gates. The synthetic topic checks
are not proof of astrological interpretation accuracy or completion of that review.
