# Coordinated recent-history release

CH7/OCH5 releases the recent-history baseline. The next coordinated versions are
SecondContext **0.2.3**, Oria application **0.2.4** and unchanged astrology MCP **0.2.1**.
The CH4–CH6 rollout is tracked in
[repeat-release evidence](evidence/conversation-history-ch7-repeat.md). Version files are
publication inputs, not proof that registry images exist. This checklist does not
automatically deploy. Record publication, selected digests and live results in
[release evidence](evidence/conversation-history-release.md).

## Compatibility and gates

Keep the existing [ownership and security boundaries](deployment.md) and the
[conversation-memory release procedure](conversation-memory-release.md). Required
schemas are Oria **0013** and SecondContext **000005**. Each owner runs its own
migration. Use the same Oria image and disclosure **2026-11-10.1** for ingress and
workers. Existing users must accept the new disclosure; old consent does not grant
permission to capture new turns. Do not rotate credentials, subject namespaces,
encryption keys, canonical user IDs or session IDs as a rollout technique.

Before publication run both repositories' `make verify`, provider history race
and image-packaging checks, and Oria `make test-history` with the intended provider
checkout. The cross-service gate covers actual HTTP replay and rollback with
synthetic model/Telegram services; it is separate from live provider quality and
private Telegram review. Compare the public contract snapshots too.

CH4/CH5 source now implements optional Decisions observation and cache diagnostics,
disabled by default. The deployed provider 0.2.2 does not contain that work; publish
and verify a compatible digest before enabling it. With observation and adaptive
disabled, current and candidate capabilities advertise
only `off` and `recent`. Observation preserves recent replay; CH6 adaptive selection
is available only through its separate opt-in. Older recall remains deferred.

The combined Compose file passes `SECOND_CONTEXT_DECISIONS_*` settings only to the
provider as `DECISIONS_*`, including its API key and independent cache-key secret.
Optional `SECOND_CONTEXT_HISTORY_GENERATION_*_USD_PER_MILLION` rates also belong
only to the provider. Oria application containers receive none of these settings.
Do not enable based on health alone: run the provider's synthetic `historyeval`
access/economics checks and preserve the existing disclosure/consent gates.
Observation rollback is `SECOND_CONTEXT_DECISIONS_OBSERVE_ENABLED=false`; it does
not change accepted history or cancel required erasure. The existing deployment
settings remain untouched. See the provider's
[configuration and evaluation guide](https://github.com/bdobrica/SecondContext/blob/main/docs/decisions-observation.md)
and [CH4/CH5 evidence](https://github.com/bdobrica/SecondContext/blob/main/docs/evidence/conversation-history-ch45.md).

## Independent capture controls

The combined Oria Compose file has separate controls so provider readiness can be
checked before callers capture history:

| Private deployment setting | Recipient | Baseline/default |
| --- | --- | --- |
| `SECOND_CONTEXT_PROVIDER_HISTORY_ENABLED` | Bundled SecondContext `HISTORY_ENABLED` | `false` |
| `SECOND_CONTEXT_HISTORY_ENABLED` | Oria gateway and worker | `false` |
| `SECOND_CONTEXT_HISTORY_RECENT_EXCHANGES` | Bundled provider | `8` |
| `SECOND_CONTEXT_HISTORY_PROMPT_INPUT_TOKENS` | Bundled provider | `65536` |
| `SECOND_CONTEXT_HISTORY_RESERVED_OUTPUT_TOKENS` | Bundled provider | `4096` |

Choose provider budgets within the configured model's supported context/output
limits; do not change the embedding model/vector size of an existing collection.
The standalone Oria file does not configure its external provider. SecondContext's
own deployment fragment uses `SECOND_CONTEXT_HISTORY_ENABLED` for its provider
switch; that fragment is not the combined Oria entry point. Keep external
SecondContext `KNOWLEDGE_ENABLED=false`. Oria's separate linked projection setting
`SECOND_CONTEXT_KNOWLEDGE_ENABLED=true` is required for source-dependent history.

## Publication and maintenance rollout

1. Commit the reviewed candidate versions and changes. Publish through the existing
   version-triggered workflows. Wait for successful Verify, cross-service and image
   publication jobs for the exact revisions. Inspect each Quay manifest and its
   source/revision/version labels; record immutable digests for both platforms.
   A successful no-op publication workflow is not an image publication receipt.
2. Use only `oria-live-test` with the existing private `deploy/.env`. Pull the
   verified digests before stopping services. Follow the owning database, key/env
   and Qdrant backup procedure in the memory release checklist. Drain gateway and
   worker, then stop SecondContext. Preserve volumes, webhook and all pending work.
3. Privately select the three verified digests, the current policy and safe model
   budgets. Set provider capture true, Oria capture false. Run each owning migration
   and start SecondContext/MCP while callers remain stopped. Check migration
   versions/clean state using their owning migration commands. Migration 000005
   never backfills old drafts as accepted dialogue.
4. Check linked capabilities/calculations and history over the actual released
   worker adapter. These commands allocate and purge only fresh synthetic subjects;
   `--generate` explicitly invokes the configured model. They send no Telegram
   messages and print no private payloads:

   ```sh
   docker compose --env-file deploy/.env -p oria-live-test -f deploy/compose.full.yaml \
     run --rm --no-deps -T worker python - --generate < scripts/check_linked_release.py
   # HISTORY_CHECK_STATE_DIR is an existing private directory outside the checkout,
   # writable only by the worker's UID 65532; retain it across container recreation.
   docker compose --env-file deploy/.env -p oria-live-test -f deploy/compose.full.yaml \
     run --rm --no-deps -T -v "$HISTORY_CHECK_STATE_DIR:/release-check:rw" worker \
     python - --generate --cleanup-journal /release-check/history-cleanup \
     < scripts/check_history_release.py
   ```

   The history check verifies exact scoped capabilities, idempotent local and
   generated acceptance, recall of random synthetic codes from local dialogue and
   an accepted replacement, linked-session erasure and full-purge retry fences.
   Without `--generate` it verifies lifecycle only. A model recall failure blocks
   this smoke gate; health or a nonempty answer cannot substitute for continuity.
   Erasure receipts establish declared HTTP coverage, not upstream retention or
   direct inspection of provider storage. Synthetic replay tests inspect exact
   model inputs separately. The history command journals only its fresh synthetic subject UUID in that
   private directory before HTTP work. It refuses to overwrite an existing journal.
   On failure, rerun the same command with `--cleanup-only` instead of `--generate`;
   successful purge removes the journal. Resolve cleanup before continuing. Never
   put this journal, private settings or generated text in release evidence.
5. Enable Oria capture only after these gates pass. Set
   `SECOND_CONTEXT_HISTORY_ENABLED=true`, retain linked projections, run
   `make deploy-check DEPLOY_PROJECT=oria-live-test`, then the documented
   `make deploy DEPLOY_PROJECT=oria-live-test`. Recheck consistent image/disclosure
   versions and both migrations. Confirm webhook registration without changing it.
6. Have an explicitly participating private Telegram user accept the new disclosure
   and exercise a short follow-up, second-option reference, correction, ordinary
   local question/answer, unrelated topic, source-linked forget and full deletion
   on a disposable account. Verify pending-work recovery and no remote forgetting
   claim before its receipt. Do not send unsolicited messages or delete an existing
   person's account to manufacture test evidence. Record only sanitized outcomes.

## Rollback without losing recovery

Rollback changes capture settings on these compatible images and schemas. Never
run the history down migration or restore a pre-CH3 provider that ignores session
fences. Downgrading to pre-OCH3 Oria also loses required work handling. Retain all
storage, migration versions, the new disclosure and existing erasure workers.

1. Quiesce gateway/worker. Set Oria `SECOND_CONTEXT_HISTORY_ENABLED=false` for both,
   keeping linked projections and the provider available. Restart the same Oria
   code with that configuration. Pending prepared generation is canceled and its
   draft abandoned; a committed generated acceptance and saved reply still finalize
   and deliver. Acceptance is not proof of Telegram delivery.
2. Let pending local acceptances finish while provider capture is still enabled.
   `accept_local` has no remote draft reservation: an undispatched local exchange
   is new provider capture. Turning off the provider first will block that exchange
   until capture is restored or its bounded consumer deadline expires. Do not
   discard its encrypted work or falsely mark it finalized.
3. If needed, disable provider capture separately and restart only that service.
   Ready discovery/new managed capture stops, but generated finalization, existing
   local receipt retries, abandonment, linked erasure and subject purge remain
   available. New Oria requests use legacy behavior. In-flight requests are not
   implicitly converted to legacy calls or regenerated under new turn IDs.
4. Resolve acceptance/delivery uncertainty through the existing five-attempt/24-hour
   lifecycle. Delivery retries can duplicate a Telegram message after an ambiguous
   send; rollback does not create an exactly-once guarantee. Erasure remains active
   after capture/LLM disablement and withdrawal.
5. Re-enable provider capture, refresh capabilities and validate the same gates
   before re-enabling Oria. Accepted history remains available, but canceled inputs,
   expired drafts and conversations handled through legacy mode are not backfilled.

See [durable workflow](conversation-history.md) and the
[release evidence](evidence/conversation-history-release.md) for executed checks and
remaining operational gates. Synthetic rollback checks are not a live rollback drill.

The bundled provider input budget is 65,536 conservative units (serialized UTF-8
bytes plus envelope allowance), with 4,096 output tokens reserved. This accommodates
full current natal/transit facts and recent dialogue; the former 32,768 default
rejected a live transit request before generation. Verify the sum against the
configured model before deployment. GPT-4.1 mini has a documented 1,047,576-token
context window ([OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini)).
The standalone provider default remains unchanged. Budget changes affect the
provider configuration binding: resolve existing pending turns before switching.


## Adaptive selection after CH6

`SECOND_CONTEXT_HISTORY_ADAPTIVE_ENABLED=false` is a provider-only capability flag.
It is independent of provider capture and recent observation. Setting it true does
not switch Oria's adapter: Oria continues sending `recent`. Keep that default;
the provider's paired synthetic evaluation preserved context but increased aggregate
cost and latency. See [CH6 evidence](evidence/adaptive-history.md).

Publish the provider before the consumer release; CI must pin that exact provider
revision. Future consumer opt-in
must freeze the requested mode with each durable prepared turn, check capability,
and drain or abandon pending adaptive work before provider disablement. Never change
a retry's header to recent. Existing generated finalization/receipts and erasure
remain available with adaptive disabled. No image, secret, policy or live setting
changes accompany this implementation, and private Telegram review remains open.
