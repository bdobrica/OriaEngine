# OriaEngine — MVP TODO

This checklist translates `PLAN.md` into a consecutive implementation path.

**Current priority: move quickly toward a working demo.** Prefer the smallest
end-to-end path through the required stages; defer optional polish and speculative
abstractions. Preserve consent, privacy, security, and component boundaries.
A demo is an intermediate milestone, not completion of the MVP release gate.

The stages are intentionally ordered so each stage leaves the repository in a testable state and provides the foundation required by the next stage. Avoid implementing post-MVP features until the MVP completion gate at the end of this document passes.

```mermaid
flowchart LR
    A[Scaffold] --> B[Identity + Consent]
    B --> C[Telegram + Onboarding]
    C --> D[Private Birth Profile]
    D --> E[Place / Time Normalization]
    E --> F[Astrology MCP]
    F --> G[Queue + Worker]
    G --> H[SecondContext]
    H --> I[Oria Persona + Policy]
    I --> J[Privacy + Deletion]
    J --> K[Webhook + Operations]
    K --> L[MVP Release Gate]
```

---

## Stage 0 — Repository bootstrap

### Goal

Create a clean Python project with predictable Makefile workflows and CI-ready tooling.

### Tasks

- [x] Create `pyproject.toml` for Python 3.12+.
- [x] Configure uv for dependency management and lock dependencies.
- [x] Add runtime dependencies:
  - [x] FastAPI;
  - [x] aiogram 3;
  - [x] Pydantic / pydantic-settings;
  - [x] SQLAlchemy 2.x;
  - [x] Alembic;
  - [x] psycopg 3;
  - [x] redis-py;
  - [x] Dramatiq Redis support;
  - [x] httpx;
  - [x] cryptography;
  - [x] FastMCP for the astrology service.
- [x] Add development dependencies:
  - [x] pytest;
  - [x] pytest-asyncio;
  - [x] pytest-cov;
  - [x] respx or equivalent HTTP mocking;
  - [x] Ruff;
  - [x] mypy or Pyright.
- [x] Create `src/oria_engine/` package.
- [x] Create `services/astrology_mcp/` package.
- [x] Create test directories for unit, integration, contract, and E2E tests.
- [x] Add `.gitignore` covering `.env`, caches, virtual environments, coverage, and local artifacts.
- [x] Add `.env.example` without real secrets.
- [x] Add a Makefile with at least:
  - [x] `help`;
  - [x] `bootstrap`;
  - [x] `env`;
  - [x] `format`;
  - [x] `lint`;
  - [x] `typecheck`;
  - [x] `test-unit`;
  - [x] `verify`;
  - [x] `clean`.
- [x] Add a minimal GitHub Actions workflow that runs `make verify`.

### Acceptance criteria

- [x] `make bootstrap` works from a clean checkout.
- [x] `make format`, `make lint`, `make typecheck`, and `make test-unit` work.
- [x] `make verify` passes with a placeholder test.

---

## Stage 1 — Configuration and application skeleton

### Goal

Build a runnable service with strict configuration and privacy-safe logging.

### Tasks

- [x] Implement typed application settings.
- [x] Support `APP_ENV` and `LOG_LEVEL`.
- [x] Support `DATABASE_URL` and `REDIS_URL`.
- [x] Support Telegram configuration variables.
- [x] Support profile-encryption configuration.
- [x] Support SecondContext base URL/auth configuration.
- [x] Support Astrology MCP URL configuration.
- [x] Fail startup on malformed required production settings.
- [x] Add structured JSON logging.
- [x] Add log redaction helpers for secrets.
- [x] Define a rule that raw birth-profile payloads are never logged.
- [x] Create FastAPI app factory.
- [x] Add `/healthz`.
- [x] Add `/readyz` with dependency checks that can be extended later.
- [x] Add graceful shutdown hooks.
- [x] Add basic request/update correlation IDs.

### Tests

- [x] Unit-test configuration parsing.
- [x] Unit-test invalid production config failure.
- [x] Unit-test secret/redaction helpers.
- [x] Test `/healthz`.

### Acceptance criteria

- [x] `make api` starts a local HTTP process.
- [x] `/healthz` returns success.
- [x] No configured secret value appears in logs during tests.

---

## Stage 2 — Local infrastructure and database migrations

### Goal

Establish PostgreSQL as canonical state and Redis as disposable coordination infrastructure.

### Tasks

- [x] Add Docker Compose services for PostgreSQL and Redis.
- [x] Add health checks for both services.
- [x] Add `make infra-up`.
- [x] Add `make infra-down`.
- [x] Add `make infra-reset` for local/test use only.
- [x] Initialize Alembic.
- [x] Add `make migrate`.
- [x] Add `make migrate-down` for development.
- [x] Add SQLAlchemy async engine/session management.
- [x] Add transaction helper/repository base conventions.

### Acceptance criteria

- [x] `make infra-up` produces healthy PostgreSQL and Redis services.
- [x] `make migrate` succeeds on an empty database.
- [x] Re-running `make migrate` is safe.

---

## Stage 3 — Core identity and consent schema

### Goal

Create durable internal identity and consent state independent of Telegram objects.

### Tasks

- [x] Add `users` table.
- [x] Add `social_identities` table.
- [x] Add unique `(provider, provider_user_id)` constraint.
- [x] Store only Telegram identifiers needed for routing.
- [x] Do not store Telegram username/display name by default.
- [x] Add `consents` table with policy version and lifecycle timestamps.
- [x] Implement user repository.
- [x] Implement social identity repository.
- [x] Implement consent repository.
- [x] Implement `get_or_create_user_for_social_identity()`.
- [x] Implement current-consent lookup.
- [x] Define policy version in configuration.

### Tests

- [x] User creation.
- [x] Identity lookup.
- [x] Duplicate identity protection.
- [x] Consent accept/decline/revoke lifecycle.
- [x] Cross-user scoping tests.

### Acceptance criteria

- [x] A Telegram provider ID resolves to exactly one internal UUID.
- [x] Consent state survives process restarts.

---

## Stage 4 — Telegram adapter: local polling baseline

### Goal

Get a real private Telegram bot receiving and sending messages with minimal domain behavior.

### Tasks

- [x] Create development bot through BotFather manually (operator confirmed).
- [x] Document BotFather setup and live smoke test in [docs/telegram.md](docs/telegram.md).
- [x] Add `TELEGRAM_BOT_TOKEN` configuration.
- [x] Build aiogram dispatcher/router.
- [x] Support private chats only.
- [x] Ignore or politely reject group/channel interactions.
- [x] Add `/start`.
- [x] Add `/help` placeholder.
- [x] Normalize Telegram updates into internal channel messages.
- [x] Implement outbound `ChannelClient` abstraction.
- [x] Implement Telegram `ChannelClient` adapter.
- [x] Add local long-polling entrypoint.
- [x] Add `make run` for local polling mode.
- [x] Ensure message text is not dumped into normal application logs.

### Tests

- [x] Telegram update normalization.
- [x] Private-chat filter.
- [x] Outbound message adapter with mocked Telegram API.

### Acceptance criteria

- [x] Sending `/start` to the development bot produces a response (operator confirmed live smoke test, 2026-09-27).
- [x] No birth data is requested yet.

---

## Stage 5 — Deterministic consent flow

### Goal

Require explicit consent before collecting or persisting birth data.

### Tasks

- [x] Write initial disclaimer text and assign a version.
- [x] Clearly state that Oria is an AI astrology personality.
- [x] State that astrology is interpretive and not a factual/scientific forecast.
- [x] State exactly which birth fields are required.
- [x] State that unrelated PII will not be solicited.
- [x] State profile/privacy/deletion controls.
- [x] Add adult-use confirmation for MVP.
- [x] Add Telegram inline buttons for accept/decline.
- [x] Implement `ConsentRequired` state from durable DB state.
- [x] Persist acceptance with policy version and timestamp.
- [x] Persist decline without collecting profile data.
- [x] If user sends possible birth data before consent, do not store it as profile data.
- [x] Add re-consent behavior when policy version changes.

### Tests

- [x] `/start` with no consent shows disclaimer.
- [x] Decline stops onboarding.
- [x] Accept advances onboarding.
- [x] Text entered before consent is not written to birth profile.
- [x] New policy version requires fresh consent.

### Acceptance criteria

- [x] No code path creates an active birth profile for a user without current consent.

Acceptance starts or resumes deterministic collection with encrypted drafts.
Draft/profile writes check current consent transactionally; activation remains
Stage 10 and must retain that check. See [consent flow](docs/consent-flow.md).
The live consent-button smoke test in [Telegram setup](docs/telegram.md) remains
an operator check; automated tests use synthetic updates and isolated PostgreSQL.

---

## Stage 6 — Birth-profile schema and encryption

### Goal

Persist the minimum calculation profile using application-level encryption.

### Tasks

- [x] Define versioned Pydantic `BirthProfilePayload` schema.
- [x] Include birth date.
- [x] Include optional birth local time.
- [x] Include `birth_time_accuracy` = `exact | approximate | unknown`.
- [x] Include normalized birthplace object.
- [x] Add `birth_profiles` table.
- [x] Store ciphertext rather than plaintext birth fields.
- [x] Store encryption key version.
- [x] Implement AES-GCM encryption service.
- [x] Use unique nonce per encryption operation.
- [x] Bind ciphertext to user/profile context with authenticated associated data where appropriate.
- [x] Implement profile repository with encrypted reads/writes.
- [x] Never expose decrypted payload in repr/logging.
- [x] Add profile schema version.
- [x] Add profile update timestamp.

### Tests

- [x] Encryption round-trip.
- [x] Wrong key fails safely.
- [x] Tampered ciphertext fails authentication.
- [x] Repository stores no plaintext test birth values.
- [x] User A cannot load user B profile.

### Acceptance criteria

- [x] Direct DB inspection cannot reveal raw birth date/time/place values.

See [birth-profile storage](docs/birth-profiles.md) for schema, key handling and
repository boundaries. Stage 7 connects collection to this consent-checked store;
Stage 8 supplies live place normalization and historical time clarification.

---

## Stage 7 — Onboarding state machine

### Goal

Collect only the allowed birth data through deterministic application states.

### Tasks

- [x] Implement onboarding state resolver from consent/profile completeness.
- [x] Add `BirthDateRequired`.
- [x] Parse supported birth-date formats.
- [x] Reject ambiguous/invalid dates with a focused retry.
- [x] Add `BirthTimeRequired`.
- [x] Support exact time.
- [x] Support approximate time.
- [x] Support unknown time.
- [x] Add `BirthPlaceRequired`.
- [x] Request city + country only.
- [x] Add `BirthPlaceConfirmation`.
- [x] Add `ProfileConfirmation` summary.
- [x] Add edit buttons for each field.
- [x] Persist profile only under the defined schema.
- [x] Do not route onboarding questions through the free-form LLM.

### Tests

- [x] Happy path with exact birth time.
- [x] Approximate time path.
- [x] Unknown time path.
- [x] Invalid date/time paths.
- [x] Editing one field.
- [x] Attempt to submit extra profile attributes is rejected by schema.

### Acceptance criteria

- [x] The only profile fields the application can solicit/store are those required by the birth-profile schema.

Encrypted drafts survive restart; final profiles require explicit confirmation.
See [onboarding](docs/onboarding.md). Live polling now uses the bundled gazetteer
and historical timezone rules; tests also retain isolated deterministic fixtures.
Stage 10 supplies calculation/activation; saved-profile controls remain Stage 17.

---

## Stage 8 — Local birthplace and historical timezone resolution

### Goal

Turn city/country and local birth time into deterministic calculation inputs without using the LLM as a geocoder.

### Tasks

- [x] Define `PlaceResolver` interface (introduced for Stage 7 candidate selection).
- [x] Select/import a local or controlled gazetteer dataset.
- [x] Implement city + country lookup.
- [x] Return multiple candidates when ambiguous.
- [x] Store selected latitude/longitude.
- [x] Resolve IANA timezone from the selected location.
- [x] Implement historical local-time conversion with `zoneinfo`.
- [x] Detect ambiguous/non-existent local times around DST transitions.
- [x] Ask the user for clarification when conversion cannot be made safely.
- [x] Preserve original local values.
- [x] Add deterministic test fixtures for multiple countries and DST cases.

### Acceptance criteria

- [x] A known city/date/time resolves reproducibly to the expected UTC instant.
- [x] No LLM call is involved in coordinate/timezone calculation.

See [place resolution](docs/place-resolution.md) for dataset coverage and refresh,
time clarification, and profile schema compatibility. Live polling can now save a
confirmed profile; Stages 9–10 remain the calculation boundary. Before calculation,
Stage 10 must clarify unresolved legacy profile times and version derived data
against the bundled timezone rules. Live Telegram smoke testing remains an operator check.

---

## Stage 9 — Astrology MCP service container

### Goal

Build the astrology calculation engine with Swiss Ephemeris and a thin Oria-owned
Python feature layer, then expose it as deterministic, structured MCP tools.
No trained model or pre-existing implementation is expected. The LLM interprets
calculated facts; it does not generate the numerical chart values. See
[PLAN section 16](PLAN.md#16-astrology-mcp-service) for component boundaries and
calculation conventions. Learned predictive models remain outside the MVP.

### Tasks

- [x] Create FastMCP server in `services/astrology_mcp/`.
- [x] Add Dockerfile for astrology MCP service.
- [x] Add service to Docker Compose private network.
- [x] Integrate Swiss Ephemeris through Python bindings and a thin Oria calculation layer.
- [x] Pin binding/engine versions and ephemeris backend/data; prevent silent backend fallback.
- [x] Document library/binding/data licensing before distribution or public service activation.
- [x] Define typed input/output schemas.
- [x] Publish supported bodies/dates, zodiac/reference frame, house system, orb rules, units and numerical tolerances.
- [x] Implement `calculate_natal_chart`.
- [x] Return longitude, zodiac sign/degree, longitude velocity and retrograde state.
- [x] Return Ascendant/MC, house cusps and placements only when valid; flag unsupported houses without silently changing systems.
- [x] Compute conjunction/opposition/square/trine/sextile with continuous separation, target angle and orb values.
- [x] Preserve relative angular velocity and supported applying/separating state with documented conventions.
- [x] Include calculation engine, binding, ephemeris/data and contract versions in output.
- [x] Include availability/uncertainty flags.
- [x] Define explicit approximate/unknown-time behavior without inventing an exact birth instant.
- [x] Do not accept Telegram/user identifiers.
- [x] Add health/readiness strategy for container orchestration.
- [x] Add `make mcp`.
- [x] Add `make mcp-test` or include in contract tests.

### Contract tests

- [x] Golden natal fixture with known exact-time chart.
- [x] Golden fixture with unknown birth time.
- [x] Document independent reference values, calculation options and tolerances for golden fixtures; do not use illustrative example JSON as a reference chart.
- [x] Cover angle wraparound, orb boundaries, retrograde/stationary motion and unavailable house calculations.
- [x] Verify no houses/ascendant are returned as authoritative when time is unknown.
- [x] Validate schema stability.

### Acceptance criteria

- [x] OriaEngine can call the container over MCP and receive a typed natal result.

Stage 9 remains focused on natal calculation. Stage 13 adds natal-to-transit
relationships. Time-to-exact may be unavailable until a validated method exists;
linear extrapolations must be marked as estimates. Declination parallels and
contra-parallels are later extensions. No outcome collection or predictive-model
training is part of this stage.

The v1 service uses the explicit built-in Moshier backend and returns unavailability
for date-only requests. See [Astrology MCP](docs/astrology-mcp.md) for the contract,
container workflow and licensing prerequisites. Stage 10 still connects confirmed
profiles to calculations; public distribution/activation still requires resolving
the engine and binding license choices.

---

## Stage 10 — Derived astrology profile

### Goal

Compute and cache the user's natal chart after profile confirmation.

### Tasks

- [ ] Add `astrology_profiles` table.
- [ ] Store calculation engine and ephemeris/data versions.
- [ ] Store source profile version/hash.
- [ ] Store derived structured result in JSONB or defined relational form.
- [ ] Implement `AstrologyClient` interface.
- [ ] Implement FastMCP client adapter.
- [ ] On profile confirmation, invoke `calculate_natal_chart`.
- [ ] Mark profile active only after successful calculation.
- [ ] If calculation fails, keep birth profile recoverable and report a retryable error.
- [ ] Invalidate derived profile after any birth-profile edit.
- [ ] Recompute after edits.

### Tests

- [ ] Successful calculation persistence.
- [ ] Failed calculation does not corrupt previous state.
- [ ] Profile edit invalidates result.
- [ ] Engine-version mismatch can trigger recomputation.

### Acceptance criteria

- [ ] `/profile` can report that a valid derived natal chart exists without recalculating it on every request.

---

## Stage 11 — Redis worker queue and user serialization

### Goal

Move slow conversation work off the Telegram ingress path and make concurrent messages safe.

### Tasks

- [ ] Configure Dramatiq Redis broker.
- [ ] Add worker entrypoint.
- [ ] Add `make worker`.
- [ ] Add `inbound_events` table.
- [ ] Persist Telegram provider update ID with unique constraint.
- [ ] Enqueue internal inbound-event ID, not decrypted profile data.
- [ ] Implement job retry policy.
- [ ] Implement maximum attempts/dead-letter visibility.
- [ ] Implement per-user Redis lock.
- [ ] Add bounded lock TTL.
- [ ] Ensure lock is released safely.
- [ ] Add processing status to inbound events.
- [ ] Make state transitions idempotent.
- [ ] Update local polling path to enqueue instead of doing slow work inline.

### Tests

- [ ] Duplicate Telegram update inserts one inbound event.
- [ ] Duplicate job execution does not repeat consent/profile mutation.
- [ ] Two jobs for one user are serialized.
- [ ] Two different users can process concurrently.
- [ ] Worker crash/retry leaves canonical state recoverable.

### Acceptance criteria

- [ ] Redis can be flushed and restarted without losing consent/profile data.

---

## Stage 12 — SecondContext adapter

### Goal

Add persistent conversational memory without exposing the raw birth profile as general semantic memory.

### Tasks

- [ ] Define `ContextProvider` interface.
- [ ] Implement SecondContext HTTP adapter.
- [ ] Configure bearer-token auth if enabled.
- [ ] Map OriaEngine internal UUID to SecondContext external user scope.
- [ ] Add `conversation_sessions` table.
- [ ] Create/reuse a stable SecondContext session per Oria conversation policy.
- [ ] Implement timeout/retry behavior.
- [ ] Implement typed response parsing.
- [ ] Decide which current astrology facts are injected ephemerally.
- [ ] Ensure raw birth date/time/place are not intentionally written as SecondContext memory items.
- [ ] Add context-memory guidance for conversational preferences and prior topics.
- [ ] Add SecondContext mock/stub for test suites.
- [ ] Define and test deletion adapter contract.
- [ ] If required, implement/contribute a scoped subject purge endpoint in SecondContext.

### Contract tests

- [ ] Correct user scope.
- [ ] Correct session reuse.
- [ ] No cross-user context.
- [ ] Downstream error handling.
- [ ] Deletion/purge behavior.

### Acceptance criteria

- [ ] A user's second conversation can reference an allowed prior conversational preference/context.
- [ ] The integration has a defined way to purge the user's SecondContext data.

---

## Stage 13 — Transit calculations and active-message routing

### Goal

Support useful personalized astrology conversations after onboarding.

### Tasks

- [ ] Add `calculate_transits` MCP tool.
- [ ] Return structured transiting positions/aspects/orbs.
- [ ] Include applying/separating state where the calculation engine supports it.
- [ ] Include time-to-exact where validated; label linear estimates and return unavailable otherwise.
- [ ] Define active-message intent schema.
- [ ] Support `natal_explanation`.
- [ ] Support `current_transits`.
- [ ] Support `transits_for_date`.
- [ ] Support `follow_up`.
- [ ] Support `unsupported_high_stakes`.
- [ ] Implement deterministic/rule-assisted routing where possible.
- [ ] Use structured LLM classification only where necessary.
- [ ] Ask for date clarification when ambiguous.
- [ ] Fetch only the astrology facts necessary for the selected path.
- [ ] Do not expose raw profile fields to the LLM when derived facts are sufficient.

### Tests

- [ ] Natal question routes without unnecessary transit calculation.
- [ ] “today” routes to current transit calculation.
- [ ] Explicit date routes to target date.
- [ ] Ambiguous date asks for clarification.
- [ ] Unknown birth time produces constrained facts.

### Acceptance criteria

- [ ] Oria can answer both natal and current/date-specific transit questions using MCP-provided facts.

---

## Stage 14 — Oria persona and methodology prompts

### Goal

Create a stable, recognizable personality while keeping facts and policy separate.

### Tasks

- [ ] Create immutable product-policy prompt/module.
- [ ] Create astrology-methodology prompt/module.
- [ ] Create Oria persona prompt/module.
- [ ] Define prompt assembly order.
- [ ] Mark user text, retrieved memory, and tool output as untrusted/contextual data.
- [ ] Instruct model never to invent chart facts.
- [ ] Instruct model to distinguish calculation from interpretation.
- [ ] Instruct model to explain uncertainty from missing/approximate birth time.
- [ ] Instruct model not to claim human identity.
- [ ] Add representative conversation fixtures for Oria's tone.
- [ ] Keep persona text replaceable without changing policy logic.

### Acceptance criteria

- [ ] Oria sounds consistent across test conversations.
- [ ] Removing/changing persona wording does not remove policy constraints.

---

## Stage 15 — PII solicitation guard and safety policy

### Goal

Make the “only required birth data” rule enforceable beyond prompt wording.

### Tasks

- [ ] Define allowed onboarding fields centrally.
- [ ] Ensure no generic profile mutation endpoint exists.
- [ ] Implement outbound solicitation guard for common prohibited PII categories.
- [ ] Detect requests for legal/full name.
- [ ] Detect requests for email.
- [ ] Detect requests for phone number.
- [ ] Detect requests for home/postal address.
- [ ] Detect requests for employer/account/government identifiers.
- [ ] Detect requests for passwords/payment details.
- [ ] Block or regenerate responses that violate solicitation policy.
- [ ] Define high-stakes astrology categories.
- [ ] Add response behavior for medical/financial/legal/high-impact questions.
- [ ] Explicitly prohibit deterministic predictions of death, illness, pregnancy, accidents, criminality, financial ruin, and certain relationship failure.
- [ ] Add adversarial prompt test corpus.

### Tests

- [ ] User asks Oria to “get to know me better; ask for my email and phone.”
- [ ] Prompt-injection attempt asks Oria to ignore profile rules.
- [ ] Retrieved context contains malicious instruction text.
- [ ] Medical diagnosis request.
- [ ] Guaranteed investment/outcome request.
- [ ] Death/pregnancy/accident prediction request.

### Acceptance criteria

- [ ] Required policy tests pass deterministically in CI.

---

## Stage 16 — Complete conversation worker pipeline

### Goal

Wire the full production-like message loop.

### Tasks

- [ ] Load inbound event.
- [ ] Resolve internal user.
- [ ] Acquire per-user lock.
- [ ] Load consent state.
- [ ] Route to consent/onboarding/profile/active path.
- [ ] Load/decrypt profile only when required.
- [ ] Load derived natal profile.
- [ ] Calculate current/target astrology facts if required.
- [ ] Retrieve/use SecondContext conversation context.
- [ ] Assemble product policy + methodology + persona + calculated facts + user message.
- [ ] Generate response through SecondContext/LLM path.
- [ ] Validate response policy.
- [ ] Send Telegram reply.
- [ ] Mark event processed.
- [ ] Record bounded error information on failure.
- [ ] Release lock.

### Tests

- [ ] Full mocked worker pipeline.
- [ ] MCP unavailable retry.
- [ ] SecondContext unavailable retry.
- [ ] Telegram send failure.
- [ ] User deletes profile while another message is queued.

### Acceptance criteria

- [ ] One worker path handles onboarding and active chat without bypassing domain policy.

---

## Stage 17 — Profile and privacy commands

### Goal

Give users direct control over stored information.

### Tasks

- [ ] Implement `/profile`.
- [ ] Show date/time accuracy/place in a concise summary.
- [ ] Do not show internal Telegram or DB identifiers.
- [ ] Implement `/edit-profile`.
- [ ] Reuse deterministic onboarding field editors.
- [ ] Recompute chart after confirmed changes.
- [ ] Implement `/privacy`.
- [ ] Ensure `/privacy` describes actual behavior, not intended behavior.
- [ ] Add `/help` final content.
- [ ] Consider `/about` if needed for AI/astrology disclosure.

### Acceptance criteria

- [ ] A user can inspect and correct every stored birth-profile field without administrator involvement.

---

## Stage 18 — End-to-end deletion workflow

### Goal

Make user deletion complete, durable, and retryable across services.

### Tasks

- [ ] Add `deletion_jobs` table.
- [ ] Implement `/delete-me` first confirmation.
- [ ] Add explicit second confirmation button.
- [ ] Block new normal processing while deletion is active.
- [ ] Delete/invalidate encrypted birth profile.
- [ ] Delete derived astrology profile.
- [ ] Purge OriaEngine session/application data according to retention design.
- [ ] Purge SecondContext subject/session/memory data.
- [ ] Delete relevant Redis keys.
- [ ] Remove Telegram identity mapping when deletion completes.
- [ ] Mark deletion job complete.
- [ ] Make every deletion step idempotent.
- [ ] Retry incomplete deletion jobs safely.
- [ ] Provide a final confirmation message without recreating durable user state unnecessarily.

### Tests

- [ ] Happy-path complete deletion.
- [ ] SecondContext unavailable midway, then retry succeeds.
- [ ] Redis unavailable does not prevent canonical deletion from completing later.
- [ ] Repeated `/delete-me` confirmation is safe.
- [ ] Deleted user starts again and is treated as a new profile/consent flow.

### Acceptance criteria

- [ ] End-to-end test proves the user's stored profile and context are no longer retrievable after deletion completes.

---

## Stage 19 — Production Telegram webhook

### Goal

Switch production ingress from polling to secure HTTPS webhooks.

### Tasks

- [ ] Add webhook route.
- [ ] Configure allowed update types.
- [ ] Validate Telegram webhook secret header.
- [ ] Reject missing/incorrect secret.
- [ ] Persist/deduplicate before enqueueing.
- [ ] Return 2xx quickly after accepted enqueue.
- [ ] Add webhook setup command/script.
- [ ] Add webhook delete/reset command/script.
- [ ] Add `make webhook-set`.
- [ ] Add `make webhook-delete`.
- [ ] Document reverse-proxy/TLS requirement.
- [ ] Keep polling mode for development only.

### Tests

- [ ] Valid webhook secret.
- [ ] Invalid/missing webhook secret.
- [ ] Duplicate update.
- [ ] Unsupported update type.
- [ ] Enqueue failure returns controlled failure behavior.

### Acceptance criteria

- [ ] Production deployment can receive Telegram updates without long polling.

---

## Stage 20 — Rate limiting and abuse controls

### Goal

Protect costs, service availability, and user isolation.

### Tasks

- [ ] Per-user inbound rate limit in Redis.
- [ ] Bound message size.
- [ ] Bound queued jobs per user.
- [ ] Bound LLM/tool execution time.
- [ ] Bound MCP response size.
- [ ] Bound SecondContext response size.
- [ ] Add backoff after repeated downstream failures.
- [ ] Add safe user-facing “temporarily unavailable” response.
- [ ] Add global emergency disable switch for LLM processing.
- [ ] Ensure abuse-control keys contain no PII beyond internal UUID/provider numeric IDs.

### Acceptance criteria

- [ ] A burst from one Telegram user cannot starve unrelated users.

---

## Stage 21 — Observability and operational readiness

### Goal

Make failures diagnosable without logging private profile data.

### Tasks

- [ ] Add structured request/job IDs.
- [ ] Add queue metrics.
- [ ] Add worker latency/error metrics.
- [ ] Add MCP latency/error metrics.
- [ ] Add SecondContext latency/error metrics.
- [ ] Add Telegram API latency/error metrics.
- [ ] Add consent funnel metrics.
- [ ] Add onboarding completion metrics.
- [ ] Add policy-block counter.
- [ ] Add deletion workflow metrics.
- [ ] Ensure metrics contain no raw profile values/message text.
- [ ] Add startup configuration summary with secrets omitted.
- [ ] Add Docker health checks.
- [ ] Add `make logs`.

### Acceptance criteria

- [ ] An operator can distinguish Telegram, queue, MCP, SecondContext, and database failures from logs/metrics without accessing user PII.

---

## Stage 22 — Integration and E2E test harness

### Goal

Make the entire MVP reproducibly testable without a real Telegram account or production LLM dependency.

### Tasks

- [ ] Add isolated test Docker Compose file/profile.
- [ ] Add PostgreSQL/Redis lifecycle to `make test-integration`.
- [ ] Add fake Telegram outbound server/client fixture.
- [ ] Add fake SecondContext fixture service.
- [ ] Run real Astrology MCP container for contract/E2E tests.
- [ ] Add sanitized Telegram update fixture files.
- [ ] Add conversation replay harness.
- [ ] Add exact-time onboarding replay.
- [ ] Add unknown-time onboarding replay.
- [ ] Add ambiguous-place replay.
- [ ] Add duplicate-update replay.
- [ ] Add profile-edit replay.
- [ ] Add PII-policy replay.
- [ ] Add high-stakes request replay.
- [ ] Add deletion replay.
- [ ] Add `make test-contract`.
- [ ] Add `make test-e2e`.
- [ ] Make `make verify` include all mandatory test lanes.

### Acceptance criteria

- [ ] CI runs the same top-level verification command documented for developers.
- [ ] No real Telegram token is required by CI.

---

## Stage 23 — Dockerized development environment

### Goal

Make the normal local workflow one command.

### Tasks

- [ ] Add OriaEngine gateway Dockerfile.
- [ ] Add worker container using same application image.
- [ ] Add Astrology MCP Dockerfile.
- [ ] Add development Docker Compose stack.
- [ ] Include PostgreSQL.
- [ ] Include Redis.
- [ ] Include gateway.
- [ ] Include worker.
- [ ] Include Astrology MCP.
- [ ] Support external/configurable SecondContext URL.
- [ ] Add health/dependency ordering without relying only on container start order.
- [ ] Add `make dev`.
- [ ] Add `make down`.
- [ ] Add `make logs`.

### Acceptance criteria

- [ ] With configured secrets, `make dev` starts the complete OriaEngine-owned stack.

---

## Stage 24 — Documentation pass

### Goal

Ensure repository documentation describes the implementation that actually exists.

### Tasks

- [ ] Reconcile README commands with the real Makefile.
- [ ] Reconcile `.env.example` with typed settings.
- [ ] Document BotFather bot creation.
- [ ] Document polling mode.
- [ ] Document webhook mode.
- [ ] Document SecondContext dependency.
- [ ] Document Astrology MCP development.
- [ ] Document profile-encryption key management for local dev.
- [ ] Document migration workflow.
- [ ] Document testing lanes.
- [ ] Document privacy/deletion behavior.
- [ ] Document known MVP limitations.
- [ ] Add architecture Mermaid diagrams if implementation changed.

### Acceptance criteria

- [ ] A new developer can reach a successful test run using only README + Make targets.

---

## Stage 25 — MVP release gate

Do not call the project MVP-complete until every item below passes.

### Functional

- [ ] Private Telegram interaction works.
- [ ] Explicit versioned consent is required.
- [ ] Birth date/time/place onboarding works.
- [ ] Exact, approximate, and unknown birth-time modes work.
- [ ] Birthplace normalization is deterministic.
- [ ] Natal chart calculation works through MCP.
- [ ] Current/date-specific transit calculation works through MCP.
- [ ] Oria can interpret calculated facts.
- [ ] SecondContext provides conversation continuity.
- [ ] `/profile` works.
- [ ] `/edit-profile` works.
- [ ] `/privacy` works.
- [ ] `/delete-me` works across all persistent systems.

### Privacy/security

- [ ] Raw birth profile is encrypted at rest.
- [ ] Birth profile is not intentionally embedded into semantic memory.
- [ ] Telegram username/display name are not unnecessarily persisted.
- [ ] Logs contain no birth-profile values or tokens.
- [ ] Cross-user isolation integration tests pass.
- [ ] Duplicate update tests pass.
- [ ] Per-user concurrent message tests pass.
- [ ] PII solicitation policy tests pass.
- [ ] High-stakes astrology policy tests pass.
- [ ] Webhook secret validation passes.

### Reliability

- [ ] PostgreSQL backup/restore has been exercised.
- [ ] Redis loss/restart has been exercised.
- [ ] Failed worker jobs are visible and retryable.
- [ ] MCP timeout behavior is tested.
- [ ] SecondContext timeout behavior is tested.
- [ ] Telegram send failure behavior is tested.

### Developer experience

- [ ] `make bootstrap` works from clean checkout.
- [ ] `make dev` works with documented configuration.
- [ ] `make test-unit` passes.
- [ ] `make test-integration` passes.
- [ ] `make test-contract` passes.
- [ ] `make test-e2e` passes.
- [ ] `make verify` passes.
- [ ] GitHub Actions invokes `make verify` successfully.

---

# Post-MVP backlog

These tasks should not block v0.1.

## Additional channels

- [ ] Define generic social-channel plugin registration.
- [ ] Instagram Professional DM adapter.
- [ ] Matrix adapter.
- [ ] Discord adapter.

## User engagement

- [ ] Explicit opt-in notification preferences.
- [ ] Scheduled daily reading.
- [ ] Weekly reading.
- [ ] Quiet hours and timezone-aware delivery.
- [ ] Unsubscribe/mute controls.

## Astrology capabilities

- [ ] Solar returns.
- [ ] Progressions.
- [ ] Declination feature family.
- [ ] Additional aspect families.
- [ ] Synastry with explicit consent/privacy model for every person's data.

## Product learning

- [ ] Structured “was this useful?” feedback.
- [ ] Conversation-level quality evaluation.
- [ ] Persona A/B experimentation without changing safety policy.

## Experimental prediction research

- [ ] Separate experimental data model from conversational memories.
- [ ] Collect timestamped prospective outcomes with explicit consent.
- [ ] Include ordinary/negative days, not only memorable events.
- [ ] Define non-astrological baselines.
- [ ] Lock predictions before observing outcomes.
- [ ] Evaluate with calibration, Brier score, log loss, and held-out data.
- [ ] Keep research results separate from user-facing deterministic claims.
