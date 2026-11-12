# SecondContext 0.3.1 compatibility release — 2026-11-12

SecondContext 0.3.1 fixes the [0.3.0 subject-echo blocker](secondcontext-0.3.0-compatibility.md).
Memory-command responses now carry the resolved authenticated subject in their
context packet, including ordinary Responses, managed acceptance and cached retries.
Oria's production scope validation is unchanged.

## Source and publication

- Provider source: `9aebe2b0718448b921bb664b5c541f04df296d7c`.
- Consumer compatibility checks/CI pin: `d2180f8884c3c83a9ed17261059ce1af82ddf72e`.
- Both jobs in the consumer [Verify workflow](https://github.com/bdobrica/OriaEngine/actions/runs/43316344320)
  passed: the aggregate gate and the real-provider cross-service suite.
- Provider [verification and image-packaging gate](https://github.com/bdobrica/SecondContext/actions/runs/43315606248)
  and [versioned publication](https://github.com/bdobrica/SecondContext/actions/runs/43315605582)
  passed for that exact provider revision.
- Published immutable image:
  `quay.io/bdobrica/secondcontext-gateway@sha256:a48dbb43be548bf14add11541cf3924f28923c14915c9f3c811c81b363e73a22`.
  The host image was pulled before maintenance. Source/version/revision labels were
  checked on both published architectures:

| Platform | Manifest digest |
| --- | --- |
| linux/amd64 | `sha256:6d8af8c52402c407260687894534f2644188d80eb784dad7882b5693c75e6437` |
| linux/arm64 | `sha256:94650331482898eb2a0cb06a9c751a1559c0883b1b3651abe5a73c6a1b109bb2` |

## Verification

- SecondContext's focused memory-command integration checks and full `make verify`
  passed against isolated real PostgreSQL/Qdrant. The provider regression covers
  subject/session echoes and stable retries for legacy, explicit and generated
  acceptance modes.
- Oria's `make test-history`: **31 passed** against the fixed provider. The recorder
  now distinguishes CL2 interpretation calls from answer generation, preserving
  duplicate-generation assertions. Additional checks cover accepted replacement
  dialogue, session separation, private-input exclusion and erasure fences in
  interpretation inputs. Both original failing command cases pass.
- Oria's `make verify`: **14 release-selection tests, 611 unit tests, 219 integration
  tests, 392 contract tests and 13 E2E tests passed**, along with formatting, lint
  and type checks. The existing installed Python environment ran the Make targets
  through a local wrapper because `uv` was absent from PATH.
- History schema/example snapshot comparison passed; no wire/schema definitions
  changed. The 0.3.1 fix adds no migration beyond 0.3.0's existing schema 000009.
- Disposable test dependencies were removed, including the astrology container
  left behind by the existing profiled fixture teardown.

These source tests use synthetic model/Telegram responses and do not establish
real-model quality or public Telegram delivery.

## Live rollout

The provider was upgraded from 0.2.3 to 0.3.1 in the existing `oria-live-test`
project. Oria remains at 0.2.4 and Astrology MCP at 0.2.1. Only
`SECOND_CONTEXT_IMAGE` changed in the private environment file; credentials,
encryption key, disclosure `2026-11-10.1`, namespace, models and capture settings
were preserved. Provider conversational learning has no enabled subjects;
external knowledge, observation and adaptive selection remain disabled.

Ingress and workers drained before provider maintenance. Owning-role checks found
no unresolved Oria ingress/history work or unexpired provider reservations under
the old history recipe. Both owner-specific database dumps, the private env/key
backup and a cold Qdrant archive were retained outside the checkout. Dump/archive
structures were inspected; restoring those backups was not exercised.

The provider applied its own migrations through **000009, clean**. Oria remains
at **0013 (head)**. The released Oria worker image passed:

- The two previously failing commands through managed Responses, exact retries,
  and legacy Responses, with correct subject echoes and synthetic-subject purge.
- `check_linked_release.py --generate`: actual linked calculations, owner isolation,
  revisions, generated reading, selective erasure and full purge.
- `check_history_release.py --generate`: recent capability, exact accepted receipts,
  actual model recall of local and accepted replacement dialogue, source-linked
  erasure and full-purge retry fences.

Caller restart exposed a retained Oria 0.2.0 migration container that could not
recognize the current schema. Compose recreated that job from the configured
0.2.4 image and completed migration successfully. It also recreated PostgreSQL
using the original shared data volume. Gateway/worker resumed, and the lifecycle
check was repeated after restart to verify provider access, acceptance and erasure.

All seven live services are healthy and both migration jobs exited successfully.
The original PostgreSQL/Qdrant volumes remain attached. Webhook registration still
matches the configured URL, with no pending updates at the final check. All
synthetic subjects were purged and their cleanup journals are empty. The 19
unrelated containers remained running without restart; no test containers remain.

The live probes sent no Telegram messages and changed no real account. Erasure
receipts establish the provider's declared active-store coverage, not removal
from backups, Telegram or upstream retention. Private Telegram conversational
review and the broader MVP gate remain separate.
