# MVP application update — 2026-11-06

## Deployment and cleanup

The active deployment is Compose project `oria-live-test`, using
`deploy/compose.full.yaml` and the existing private `deploy/.env`. Before this
update, gateway and worker ran the October 29 local application image.

The application image was built from verified commit
`cfcad4a21ad7760f13b7ad6e63355e08021bbfbd`, tagged
`oria-live-test:dialogue-cfcad4a`, with image ID
`sha256:9d205dae632428d4ce7b1cd8eafd243586b02a26cb9f9f10688f231ed5ef36bb`.
Its prompt headers identify `oria-voice-2`, `oria-methodology-3` and
`oria-policy-3`.

Only gateway and worker were stopped/recreated. This prompt update adds no
migration; PostgreSQL, Redis, Astrology MCP, SecondContext and Qdrant were left
running. No data volume was removed. Only `ORIA_APP_IMAGE` changed in the
deployment env; its mode remains `0600`. Credentials, encryption settings and
Telegram registration were preserved. The prior application image remains
available locally.

Removed three leftover `oria-test-*` Astrology MCP containers belonging to
projects `oria-test-8e4f163e9f4a`, `oria-test-ecbf6196e1d4` and
`oria-test-b02874853470`, plus the two successfully completed migration
containers in `oria-live-test`. Other projects were not modified. No host-wide
prune was performed.

## Verification

- Quiet Compose validation and the application image build passed.
- All seven persistent MVP services were healthy after the update. Gateway and
  worker resolved to the application image ID above.
- Gateway liveness/readiness returned 200.
- Private and public HTTPS webhook requests without a secret returned 403;
  authenticated malformed JSON returned 400. No update was admitted.
- Telegram reported the expected webhook URL and update types, zero pending
  updates and no reported delivery error. Registration was inspected, not changed.
- Oria's private operator snapshot reported healthy database/Redis checks,
  zero pending/processing/ready/dead jobs and zero queue depth.

No user message was sent. These checks do not establish live-model dialogue
quality or complete the remaining MVP release gate. The full code verification
for this source commit is recorded in [dialogue review](dialogue-review.md).

## Registry release pending

The operator requested published Quay images. Pulls for
`quay.io/bdobrica/oria-engine:latest` and
`quay.io/bdobrica/oria-astrology-mcp:latest` returned `manifest unknown`.
GitHub run `38136550224` completed release selection but skipped publication;
remote `main` was still `85cba8c16eb3fac502bc5cef74e451ca22c74ba9`, with both
image versions at baseline `0.1.0`.

Both image version files are prepared for `0.1.1`. Publication requires pushing
the reviewed release commit to `main` and confirming the publishing workflow
succeeds. Until publication and a subsequent registry deployment are verified,
the active application remains the local image above; do not describe it as a
Quay deployment. Registry deployment should pin the published digests in the
existing private env file and retain project `oria-live-test`.
