# MVP Quay deployment — 2026-11-06

## Active deployment

The active Telegram MVP is Compose project `oria-live-test`, using
`deploy/compose.full.yaml` and the existing private `deploy/.env`. Gateway,
worker and Astrology MCP now run published Quay release `0.1.1`, built from
commit `18f846b2e85ae08b95ecbc4534d0d3f18421d6fe`. Both image references are
pinned in the private env file:

| Image | Manifest digest |
| --- | --- |
| `quay.io/bdobrica/oria-engine:0.1.1` | `sha256:c286cbf885de269e7bbfcb7267bdcaa3b38d33d00a21e3c394612c5ecbca3f8d` |
| `quay.io/bdobrica/oria-astrology-mcp:0.1.1` | `sha256:07cd193db631d46de0ac14f313572f9666787dfbdd676fad024b2888eefd8681` |

The release includes the dialogue changes from `cfcad4a` and prior relative-time
support. Prompt headers identify `oria-voice-2`, `oria-methodology-3` and
`oria-policy-3`. The Python package version remains independent of image versions.

## Publication and rollout

Initially, both Quay tag lists were empty. The prior publishing workflow had
skipped publication because both image versions remained at the `0.1.0` baseline;
remote `main` still pointed to `85cba8c`. Both version files were increased to
`0.1.1`, tested and pushed with the local implementation commits. The
[publishing workflow](https://github.com/bdobrica/OriaEngine/actions/runs/42304573881)
successfully published both images for AMD64 and ARM64. The release's
[full CI verification](https://github.com/bdobrica/OriaEngine/actions/runs/42304573997)
also passed. The 14 release-selection tests passed locally, and selection against
the actual remote baseline identified both `0.1.1` images.

The MVP first received a locally built dialogue image while publication was
being established. That intermediate application image is no longer deployed.
For the final rollout, both published images were pulled and their OCI release
versions/revisions verified before updating only the two Oria image settings.
The existing env file remains mode `0600`; credentials, encryption settings and
Telegram registration were preserved.

Quiet Compose validation passed. Gateway and worker were stopped, a one-off
Oria migration job completed successfully, and only gateway, worker and Astrology
MCP were recreated with the pinned Quay images, using `--no-deps --no-build
--pull never`. Oria's schema remains `0009`; this release introduced no migration
beyond the already deployed schema. PostgreSQL, Redis, SecondContext and Qdrant
were not restarted or upgraded. No data volume was removed, and the prior local
images remain available.

Removed three leftover `oria-test-*` Astrology MCP containers belonging to
projects `oria-test-8e4f163e9f4a`, `oria-test-ecbf6196e1d4` and
`oria-test-b02874853470`, plus the two successfully completed migration
containers in `oria-live-test`. The final migration job used `--rm`. Other
projects were not modified. No host-wide prune was performed.

## Final verification

- All seven persistent MVP services were healthy. Gateway, worker and Astrology
  MCP identified release revision `18f846b2e85ae08b95ecbc4534d0d3f18421d6fe`
  and image version `0.1.1`.
- Gateway liveness/readiness returned 200.
- Private and public HTTPS webhook requests without a secret returned 403;
  authenticated malformed JSON returned 400. No update was admitted.
- Telegram reported the expected webhook URL and update types, zero pending
  updates and no reported delivery error. Registration was inspected, not changed.
- Oria's private operator snapshot reported healthy database/Redis checks,
  zero pending/processing/ready/dead jobs and zero queue depth. An Oria-owned
  schema-version read confirmed revision `0009`; no profile values were read.
- No `oria-test-*` containers remained.

No user message was sent. These checks do not establish live-model dialogue
quality or complete the remaining MVP release gate. The full local code
verification is recorded in [dialogue review](dialogue-review.md).
Use the [existing-MVP commands](../deployment.md#existing-mvp-server) for future
operations, retaining the same Compose project and private configuration.
