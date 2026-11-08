# Coordinated conversation-memory release

This release combines natural dates, encrypted canonical entities/events, scoped
SecondContext salience and linked interpretations, and compatibility/event charts.
The broader [MVP gate](../TODO.md#stage-25--mvp-release-gate) remains separate.

## Consent and compatibility

The disclosure version is `2026-11-08.5`. It covers voluntary sharing and local
learning, the optional projection/session lifecycle, opt-out, calculated readings,
date-only noon-UTC samples and symbolic ratings. It fits Telegram's single-message
limit even with a 64-character custom version. Known older versions are rejected
at ingress/worker startup. Operators using custom versions must bump them too.
Existing users must explicitly accept the new version before learning or readings
resume. Old consent buttons cannot accept the current policy. Inspection and
erasure remain available without acceptance; withdrawal keeps pending erasure alive.
No additional consent from mentioned people or registration for entities is needed.
General disclosures remain in consent/help/privacy, outside ordinary readings.

Required schema heads are Oria `0012` and SecondContext `000004`. The owning
services run their own migrations; Oria never accesses SecondContext storage.
Legacy natal/transit and response consumers remain compatible. New linked readings
require matching application/MCP images; projections require the authenticated
`linked-context-1` capability, including linked-session erasure. Oria's existing
`SECOND_CONTEXT_KNOWLEDGE_ENABLED` switch defaults off; set it true only for a
verified compatible release. SecondContext's separate `KNOWLEDGE_ENABLED` integration
targets an external knowledge service and stays disabled. Linked projections use
SecondContext's own migrated PostgreSQL and authenticated capability instead.

## Verification and publication

1. Run focused consent, natural-date, canonical/projection and linked-reading
   checks, then `make verify`. E2E fixtures use synthetic Telegram/provider HTTP
   responses, real isolated PostgreSQL/Redis, and the real private MCP container.
   They do not establish live model quality or public Telegram delivery.
2. Verify SecondContext in its owning repository, including mandatory dependency
   tests for stale revisions, linked sessions/drafts/context, selective erase and
   full purge. Consumer mocks are not substitutes for those tests.
3. Increase both Oria image versions and the required SecondContext gateway version.
   Publish through the repositories' version-triggered GitHub Actions workflows.
   Confirm successful Verify/publication runs and inspect the published manifests
   and source/version labels before selecting immutable Quay digests.

## Oria-only maintenance rollout

Use the existing `oria-live-test` project and private `deploy/.env`. Preserve its
encryption key, credentials, bot/webhook, volumes and namespace. Never start another
project with this bot or prune unrelated host resources.

1. Pull the verified digests before stopping services. Drain gateway and worker,
   then stop bundled SecondContext. Back up both databases under their respective
   owners, the private environment/encryption key and compatible Qdrant storage.
   A cold storage backup requires stopping only Oria's Qdrant after its API drains.
   Store sensitive backups privately outside the checkout; do not commit them.
2. Privately select the three digests and `ORIA_POLICY_VERSION=2026-11-08.5`.
   Keep linked memory off and callers stopped while starting the selected
   infrastructure, owning migration jobs, SecondContext and MCP. Run Oria's migration
   with `run --rm --no-deps migrate`; `up --wait secondcontext` waits for its migration
   dependency. Run the synthetic
   check below with `run --rm --no-deps -T worker` instead of `exec -T worker` to
   verify capability/provider/erasure before ingestion starts. Then set
   `SECOND_CONTEXT_KNOWLEDGE_ENABLED=true`, run `make deploy-check` and
   `make deploy DEPLOY_PROJECT=oria-live-test`. Only selected Oria services migrate
   and restart. Keep the backup for recovery; downgrading images does not undo schema.
3. Check both migration jobs, service health and private gateway readiness. Confirm
   configured versions/switches without printing interpolated secrets. Check actual
   capability and calculations, not just health. From this checkout:

   ```sh
   docker compose --env-file deploy/.env -p oria-live-test -f deploy/compose.full.yaml \
     exec -T worker python - --generate < scripts/check_linked_release.py
   ```

   This explicitly calls the configured AI provider with synthetic inputs, checks
   both new MCP tools, scoped projection/query, duplicate operations, correction,
   stale generation rejection, selective erase/resurrection fences and full purge.
   It allocates fresh synthetic subjects and purges only those subjects in cleanup;
   no Telegram send or real account mutation is performed. Output withholds payloads,
   credentials and generated text. An erase receipt establishes the owning service's
   declared coverage; it is not direct inspection of that service's storage.
4. Verify webhook registration without changing it. A real private Telegram user
   should then review new consent, onboarding or their existing profile, a natural
   date, a partner/event reading, recall, correction and deletion. Sending to real
   users needs their explicit request; synthetic HTTP replays do not prove this step.
5. Record source revisions, image digests, checks and remaining manual review in
   [release evidence](evidence/conversation-memory-release.md). Keep private runtime
   payloads and unrelated operational incidents out of the repository.

If a verification fails, keep ingestion disabled or stop the affected Oria callers
until compatible services are restored. Retrying selective erasure remains enabled
even after learning is disabled. Do not reset volumes or discard pending work.
