# OriaEngine — MVP Plan

## 1. Purpose

OriaEngine is the application runtime for **Oria**, an AI astrology personality that lives inside messaging and social platforms and maintains an ongoing relationship with each user.

The first MVP will run as a **Telegram bot**. Users will be able to start a private conversation with Oria, explicitly consent to the collection and use of the minimum birth information required for astrological calculations, create a persistent birth profile, and ask for personalized astrological interpretations and reflective guidance.

OriaEngine is intended to build on the ideas and infrastructure of [SecondContext](https://github.com/bdobrica/SecondContext): persistent user-scoped context, structured memory, retrieval, and conversation continuity. OriaEngine adds the channel integration, consent/profile state machine, privacy boundary, astrology calculation service, and Oria-specific policy/persona layer.

The MVP is not intended to establish astrology as scientifically validated or causally predictive. Astrological calculations are treated as deterministic inputs to an interpretive experience. Oria must clearly distinguish computed chart facts from traditional astrological interpretation and from general conversational advice.

---

## 2. MVP hypothesis

The first product hypothesis is:

> A persistent AI astrology personality that remembers a user's chart and prior conversations can create a more useful and engaging experience than a stateless astrology chatbot, while collecting only the information needed to perform the calculations and keeping that information under explicit user control.

The MVP should demonstrate that the system can:

1. receive and reply to private Telegram messages;
2. obtain explicit, versioned user consent before collecting birth data;
3. collect only the birth information required for the astrological model;
4. normalize that information into a mathematically usable birth instant and location;
5. persist the user's private profile securely in PostgreSQL;
6. call a deterministic astrology calculation service exposed through FastMCP;
7. build and persist a derived natal profile;
8. use SecondContext for conversational continuity and non-sensitive long-term context;
9. generate answers in Oria's stable personality while grounding chart claims in calculated data;
10. prevent Oria from soliciting unrelated personally identifiable information;
11. provide privacy, profile editing, consent withdrawal, and deletion controls;
12. run locally and in CI through simple Makefile workflows.

---

## 3. Product identity

### Repository

**OriaEngine**

### Persona

**Oria**

Oria is the user-facing personality. OriaEngine is the technical system that hosts and governs her.

Oria should feel like a consistent, recognizable astrologer rather than a generic assistant with an astrology prompt. However, she must remain transparent about being an AI personality and must never claim to be a human astrologer.

A useful separation is:

- **OriaEngine** — application, policies, state machines, integrations, storage, orchestration;
- **Oria** — personality, language, tone, conversational behavior;
- **SecondContext** — persistent conversational memory and context;
- **Astrology MCP** — deterministic mathematical calculation service.

---

## 4. Scope

### 4.1 In scope for v0.1

The MVP includes:

- Telegram private-message interaction;
- `/start`, `/help`, `/profile`, `/edit-profile`, `/privacy`, and `/delete-me` commands;
- explicit consent before birth data is collected or stored;
- adult-use confirmation for the initial public MVP;
- birth date collection;
- birth time collection with exact, approximate, and unknown states;
- birthplace collection using city and country, with disambiguation when necessary;
- local/controlled birthplace normalization to latitude, longitude, and IANA timezone;
- historical local-time to UTC conversion;
- encrypted persistent birth-profile storage in PostgreSQL;
- deterministic natal-chart generation;
- deterministic transit/aspect calculation for a requested date or the current date;
- astrology calculation service in a separate Docker container using FastMCP;
- Redis-backed job processing and temporary state;
- per-user processing locks;
- idempotent inbound Telegram update handling;
- SecondContext integration for user-scoped conversational memory;
- structured persona and safety policy layers;
- privacy-aware structured logging;
- unit, integration, contract, and replay-based end-to-end tests;
- Docker Compose for local infrastructure;
- Makefile-based development and verification workflows.

### 4.2 Explicitly out of scope for v0.1

The first version will not include:

- Instagram integration;
- public Telegram group participation;
- unsolicited outbound messaging;
- scheduled daily horoscopes;
- autonomous posting to social networks;
- payments or subscriptions;
- multiple AI personas;
- voice or image interactions;
- relationship/synastry profiles involving another person's birth data;
- custom predictive machine-learning models;
- learning astrological rules from user outcomes;
- automated ingestion of medical, financial, employment, relationship, or other life-event datasets;
- medical, legal, financial, diagnostic, or other high-stakes advice;
- deterministic claims about death, illness, pregnancy, accidents, criminal behavior, financial ruin, or definite relationship outcomes.

These can be considered after the core interaction, privacy model, and calculation pipeline have been validated.

---

## 5. User experience

## 5.1 First interaction

A first-time user opens a private Telegram chat and sends `/start` or any message.

OriaEngine does **not** immediately ask for birth data. The user first receives a concise disclosure explaining:

- Oria is an AI astrology personality;
- astrology is interpretive and should not be treated as factual or scientific prediction;
- the system needs birth date, birth time, and birthplace to perform chart calculations;
- those details will be stored for future conversations if the user continues;
- the system will not solicit unrelated PII;
- the user can inspect, edit, or delete the stored profile;
- the service is intended for adults in the MVP;
- high-stakes decisions should not be based on Oria's responses.

The disclosure is versioned. The user must explicitly choose an **Agree** action before profile collection starts.

A starting disclosure can be:

> Hi — I’m Oria, an AI astrology personality. If you want a personalized reading, I need your birth date, birth time (exact, approximate, or unknown), and birthplace (normally city and country) so I can calculate your chart. If you continue, OriaEngine will store those details for future conversations. I won’t ask you for unrelated identifying information such as your legal name, email, phone number, home address, employer, passwords, government IDs, or payment details. You can inspect, correct, or delete your stored profile at any time. Astrology is an interpretive practice, not a scientifically established forecasting method, and my responses should not be used as medical, legal, financial, or other high-stakes professional advice. The MVP is intended for adults. Do you agree and want to continue?

The exact wording is product copy and can be iterated, but the data categories, AI disclosure, purpose, storage, user controls, high-stakes limitation, and affirmative-consent requirement are product invariants.

If the user sends birth information before accepting, OriaEngine must not persist it as profile data. It should restate the consent requirement and ask the user to accept or decline.

## 5.2 Profile onboarding

After consent, onboarding follows a deterministic state machine rather than an LLM-driven interview.

```mermaid
stateDiagram-v2
    [*] --> ConsentRequired
    ConsentRequired --> Closed: Decline
    ConsentRequired --> BirthDateRequired: Accept

    BirthDateRequired --> BirthTimeRequired: Valid date
    BirthTimeRequired --> BirthPlaceRequired: Exact / approximate / unknown
    BirthPlaceRequired --> BirthPlaceConfirmation: Candidate location(s)
    BirthPlaceConfirmation --> ProfileConfirmation: Location selected / safe or unknown time
    BirthPlaceConfirmation --> BirthTimeClarification: Repeated or non-existent local time
    BirthTimeClarification --> ProfileConfirmation: Choose occurrence or unknown
    BirthTimeClarification --> BirthDateRequired: Correct date
    BirthTimeClarification --> BirthTimeRequired: Correct time
    BirthTimeClarification --> BirthPlaceRequired: Correct place
    ProfileConfirmation --> BirthDateRequired: Edit date
    ProfileConfirmation --> BirthTimeRequired: Edit time
    ProfileConfirmation --> BirthPlaceRequired: Edit place
    ProfileConfirmation --> ComputingProfile: Confirm
    ComputingProfile --> Active: Calculation succeeds
    ComputingProfile --> ProfileConfirmation: Calculation fails / needs correction

    Active --> BirthDateRequired: Edit profile
    Active --> DeleteConfirmation: /delete-me
    DeleteConfirmation --> Active: Cancel
    DeleteConfirmation --> Deleted: Confirm
    Deleted --> [*]
```

The application, not the LLM, decides which profile field is currently allowed to be requested.

### Birth date

Accepted in a small set of unambiguous formats and normalized to ISO-8601 date form.

### Birth time

The user can select:

- exact time;
- approximate time;
- unknown time.

The profile records `birth_time_accuracy` so the astrology service and Oria can reason about limitations. If the time is unknown, Oria must not invent ascendant, house placements, or other time-dependent facts.

### Birthplace

The system requests only what is necessary to resolve the calculation location, normally **city + country**. If a place is ambiguous, the system presents candidate places for selection instead of asking for unrelated identifying information.

A normalized birthplace contains:

- display name;
- city;
- region when needed for disambiguation;
- country code;
- latitude;
- longitude;
- IANA timezone identifier.

### Confirmation

Before the profile is persisted as active, the user sees a summary and explicitly confirms it.

---

## 6. Active conversation behavior

Once onboarding succeeds, Oria behaves as a persistent astrology personality.

Typical supported requests include:

- “What stands out in my natal chart?”
- “Explain my Venus placement.”
- “What themes are active for me this week?”
- “What are the important transits today?”
- “How would you interpret this period for career reflection?”
- “Why does this month feel unusually intense?”
- “What should I pay attention to around this date?”

The response pipeline must distinguish three layers:

1. **Computed facts** — values returned by the astrology service;
2. **Astrological interpretation** — traditional or configured interpretation of those facts;
3. **Reflective advice** — non-deterministic suggestions framed as options for reflection, not commands or factual forecasts.

Oria must never fabricate a chart value that was not supplied by the calculation service.

If a required fact is unavailable, Oria should say so. For example, if birth time is unknown, she should explicitly note that houses or ascendant-based interpretations are unavailable or unreliable.

---

## 7. Architecture

```mermaid
flowchart TD
    TG[Telegram User] --> TGA[Telegram Bot API]
    TGA --> GW[OriaEngine Gateway<br/>FastAPI + aiogram]

    GW --> IN[(PostgreSQL<br/>Inbound event / identity / consent)]
    GW --> RQ[Redis<br/>Queue + locks + temporary state]
    RQ --> WK[OriaEngine Worker]

    WK --> DB[(PostgreSQL<br/>Profiles + canonical app state)]
    WK --> CTX[SecondContext<br/>Persistent conversational context]
    WK --> MCP[Astrology MCP<br/>FastMCP container]

    MCP --> MODEL[Existing mathematical<br/>astrology model]

    WK --> POL[Policy + Persona<br/>response construction]
    POL --> TGA

    DB -. source of truth .-> WK
    RQ -. disposable coordination .-> WK
```

### 7.1 Architectural rules

1. **PostgreSQL is canonical.**
2. **Redis is disposable.** Losing Redis must not lose profile or consent data.
3. **Telegram is a transport adapter, not the domain model.**
4. **Birth data does not become general semantic memory.**
5. **Astrology calculations are deterministic and externalized behind MCP.**
6. **The LLM interprets calculated facts; it does not calculate or invent them.**
7. **Policy outranks persona.** Persona instructions cannot override privacy or safety rules.
8. **All processing is user-scoped.** A worker must never access another user's profile or context.
9. **Inbound processing is idempotent.** Telegram retries or worker retries must not create duplicate state transitions.
10. **No raw sensitive values in application logs.**

---

## 8. Technology choices

### Application

- Python 3.12+;
- FastAPI for HTTP application endpoints and webhook hosting;
- aiogram 3 for Telegram Bot API integration;
- Pydantic for configuration and domain schemas;
- SQLAlchemy 2.x for persistence;
- Alembic for migrations;
- psycopg 3 async driver;
- redis-py for Redis access;
- Dramatiq with Redis broker for background jobs;
- httpx for service-to-service HTTP clients;
- `cryptography` for application-level profile encryption;
- pytest for tests;
- Ruff for linting/formatting;
- mypy or Pyright for static type checking;
- uv for dependency/environment management behind Make targets.

### Infrastructure

- PostgreSQL;
- Redis;
- Docker / Docker Compose;
- SecondContext as an external/internal service;
- FastMCP-based astrology service in its own container.

### Why a worker queue

Telegram webhook handlers should acknowledge updates quickly. LLM calls and astrology computation may take materially longer than a webhook request should remain open.

The gateway therefore validates and persists an inbound update, enqueues work, and returns success. A worker owns the slower conversation pipeline.

Dramatiq is selected for the initial implementation because it provides a simple Redis-backed task model, retries, and worker processes without requiring the broader operational surface of Celery. Jobs must still be designed to be idempotent.

---

## 9. Suggested repository layout

The repository should be organized by domain responsibilities rather than by Telegram handlers alone.

- `src/oria_engine/app.py` — FastAPI application assembly;
- `src/oria_engine/config.py` — environment configuration;
- `src/oria_engine/domain/` — consent, onboarding, profile, policy, and conversation domain logic;
- `src/oria_engine/telegram/` — Telegram adapter, handlers, keyboards, update normalization, outbound client;
- `src/oria_engine/db/` — SQLAlchemy models and repositories;
- `src/oria_engine/queue/` — Dramatiq broker, actors, per-user locking;
- `src/oria_engine/context/` — SecondContext adapter;
- `src/oria_engine/astrology/` — MCP client and calculation contracts;
- `src/oria_engine/persona/` — Oria persona and response prompt construction;
- `src/oria_engine/privacy/` — encryption, redaction, deletion orchestration;
- `src/oria_engine/observability/` — logging and metrics;
- `services/astrology_mcp/` — FastMCP service wrapping the mathematical model;
- `migrations/` — Alembic migrations;
- `tests/unit/` — pure and mocked tests;
- `tests/integration/` — Postgres/Redis/service integration tests;
- `tests/contract/` — MCP and SecondContext API contract tests;
- `tests/e2e/` — Telegram update replay tests;
- `deploy/` — Docker Compose and production deployment examples;
- `Makefile` — developer workflows;
- `.env.example` — documented configuration template;
- `PLAN.md` — architecture and product plan;
- `TODO.md` — consecutive implementation checklist;
- `README.md` — repository front page.

---

## 10. Channel abstraction

Although v0.1 is Telegram-only, domain logic must not depend on Telegram-specific objects.

Incoming Telegram updates are normalized to an internal message structure such as:

```json
{
  "provider": "telegram",
  "provider_user_id": "123456789",
  "provider_chat_id": "123456789",
  "provider_message_id": "912",
  "provider_update_id": "77889900",
  "received_at": "2026-09-07T16:00:00Z",
  "text": "What is going on astrologically this week?"
}
```

A future Instagram or Matrix adapter should produce the same domain message form.

Likewise, outbound responses should pass through a channel interface instead of invoking aiogram directly from domain services.

---

## 11. Telegram transport

### Local development

Local development should support **long polling** so a developer can run the bot without a public HTTPS endpoint.

### Production

Production should use a Telegram webhook.

The webhook configuration must include Telegram's webhook secret token and validate the `X-Telegram-Bot-Api-Secret-Token` header before accepting the update.

The gateway must:

1. validate the secret;
2. deserialize the update;
3. ignore unsupported chat/update types;
4. persist or deduplicate the inbound event;
5. enqueue work;
6. return a successful HTTP response quickly.

Private chats are the only supported chat type in the MVP.

---

## 12. Identity model

Telegram identifiers are transport identifiers, not OriaEngine user identifiers.

Each OriaEngine user receives an internal UUID.

```mermaid
erDiagram
    USERS ||--o{ SOCIAL_IDENTITIES : has
    USERS ||--o{ CONSENTS : grants
    USERS ||--o| BIRTH_PROFILES : owns
    USERS ||--o{ CONVERSATION_SESSIONS : has
    USERS ||--o{ INBOUND_EVENTS : receives

    USERS {
        uuid id PK
        timestamptz created_at
        timestamptz deleted_at
    }

    SOCIAL_IDENTITIES {
        uuid id PK
        uuid user_id FK
        string provider
        string provider_user_id
        string provider_chat_id
        timestamptz created_at
    }

    CONSENTS {
        uuid id PK
        uuid user_id FK
        string policy_version
        string status
        timestamptz accepted_at
        timestamptz revoked_at
    }

    BIRTH_PROFILES {
        uuid id PK
        uuid user_id FK
        bytes encrypted_payload
        string encryption_key_version
        int schema_version
        timestamptz created_at
        timestamptz updated_at
    }

    INBOUND_EVENTS {
        uuid id PK
        uuid user_id FK
        string provider
        string provider_update_id
        string status
        timestamptz received_at
        timestamptz processed_at
    }
```

The application should store only the Telegram identifiers required to route replies. Telegram display name, username, phone number, profile photos, and other available metadata should not be copied into the profile unless a future feature has a documented need and explicit policy change.

---

## 13. Consent model

Consent is a durable record, not a prompt-memory fact.

A consent record contains at minimum:

- internal user ID;
- policy/disclaimer version;
- accepted/declined/revoked state;
- channel;
- acceptance timestamp;
- optional locale/version metadata needed to prove which text was displayed.

A new disclaimer version can force re-consent if the data use materially changes.

No birth profile may become active without current consent.

No LLM response should be allowed to bypass this state machine.

---

## 14. Private birth-profile storage

Birth date, birth time, and birthplace are private profile fields. They must not be stored as ordinary SecondContext memories or embedded into a vector database.

For the MVP, the recommended storage model is a single application-encrypted payload using an authenticated cipher such as AES-GCM. The database row stores ciphertext and key version; the encryption key is provided separately through the runtime secret configuration.

The decrypted payload may contain:

```json
{
  "birth_date": "1990-04-13",
  "birth_local_time": "03:42:00",
  "birth_time_accuracy": "exact",
  "birth_place": {
    "city": "Cluj-Napoca",
    "region": "Cluj",
    "country_code": "RO",
    "latitude": 46.7712,
    "longitude": 23.6236,
    "timezone": "Europe/Bucharest"
  }
}
```

The versioned payload and encryption/storage boundary are defined in
[Birth profiles](docs/birth-profiles.md). Calculation version belongs to the
derived astrology profile; raw storage carries schema and encryption key versions.

### Derived chart data

Natal chart results may be stored separately as structured JSONB with:

- calculation engine version;
- input profile version/hash;
- calculation timestamp;
- normalized UTC birth instant if available;
- planetary positions;
- houses when available;
- angles when available;
- aspect set;
- relevant precision/quality flags.

Derived data is still private and user-scoped even though it is not raw PII.

---

## 15. Birthplace and timezone normalization

The mathematical pipeline must not send birth data to an LLM in order to determine coordinates or timezone.

Preferred MVP behavior:

1. resolve typed city/country against a local or controlled gazetteer dataset;
2. offer candidate matches if ambiguous;
3. use the selected coordinates to resolve an IANA timezone;
4. use Python `zoneinfo` / the IANA timezone database to interpret the local birth time at the historical birth date;
5. convert the local instant to UTC;
6. preserve the original local values and accuracy metadata.

External geocoders may be added behind an interface, but a local resolver is preferable for privacy and deterministic testing.

Time conversion must be covered with regression fixtures around DST and historical timezone changes.

The demo uses bundled GeoNames city records, including their location-specific
IANA timezone assignments, and a fixed TZif snapshot. Repeated local times require
an explicit occurrence choice; gaps require correction or unknown time. Original
local values are preserved in encrypted profile schema 2; schema 1 remains readable.
See [place resolution](docs/place-resolution.md) for coverage, compatibility and
dataset generation. Stage 10 must version derived calculations against the source
profile and timezone snapshot, and clarify unresolved legacy times before use.

---

## 16. Astrology MCP service

The mathematical model runs in a separate Docker container and is exposed through FastMCP over the private application network.

The service should be **stateless with respect to user identity**. It should receive mathematical inputs rather than Telegram identities or usernames.

```mermaid
flowchart LR
    W[Oria worker] --> C[MCP client]
    C --> S[FastMCP Astrology Service]
    S --> M[Mathematical model]
    M --> S
    S --> C
    C --> W
```

### Initial MCP tools

The exact functions depend on the existing mathematical model, but the contract should resemble:

#### `calculate_natal_chart`

Inputs:

- UTC birth instant when known;
- local birth date when time is unknown;
- latitude;
- longitude;
- calculation options/model version.

Outputs:

- planetary positions;
- angles when valid;
- houses when valid;
- aspects;
- calculation metadata;
- uncertainty/availability flags.

#### `calculate_transits`

Inputs:

- natal chart or normalized natal features;
- target UTC timestamp/date;
- calculation options.

Outputs:

- transiting positions;
- natal-to-transit aspects;
- orb distances;
- applying/separating state where supported;
- time-to-exact values where supported;
- model/calculation metadata.

#### Optional later tools

- `calculate_solar_return`;
- `calculate_progressions`;
- `calculate_synastry` only after a separate privacy design exists.

### Tool design rules

Good MCP tools expose deterministic calculations.

They should **not** expose tools such as:

- `predict_if_user_will_break_up`;
- `decide_whether_user_should_quit_job`;
- `diagnose_health_from_chart`.

Interpretation belongs in the conversational layer and remains bounded by policy.

---

## 17. SecondContext integration

SecondContext provides the persistent context layer for conversations.

OriaEngine should implement a small `ContextProvider` abstraction so SecondContext is an adapter rather than a hard-coded dependency throughout the application.

A conversation request should be user-scoped and include:

- internal OriaEngine user ID as the external subject identity;
- stable session ID;
- current user message after privacy filtering required by the application;
- current conversational goal/intent when available;
- structured **ephemeral** astrology facts needed for the answer;
- persona/methodology hints required to produce the Oria response.

Birth date, exact birth time, and birthplace should not be promoted into general SecondContext semantic memories.

SecondContext is appropriate for memories such as:

- the user prefers concise readings;
- a previous conversation focused on career themes;
- the user asked for less mystical language;
- a transit interpretation was previously explained;
- the user prefers uncertainty to be made explicit.

### Deletion dependency

A complete `/delete-me` implementation requires a reliable way to purge all SecondContext data associated with the OriaEngine subject ID.

If SecondContext does not expose a scoped subject-purge endpoint, one should be added or a compatible deletion mechanism must be implemented before calling the MVP privacy workflow complete.

---

## 18. Conversation orchestration

For the MVP, OriaEngine should orchestrate tool use explicitly rather than relying entirely on unconstrained LLM tool selection.

```mermaid
sequenceDiagram
    participant U as User
    participant T as Telegram
    participant G as Gateway
    participant R as Redis Queue
    participant W as Worker
    participant P as PostgreSQL
    participant A as Astrology MCP
    participant S as SecondContext

    U->>T: Send DM
    T->>G: Update webhook
    G->>P: Deduplicate/persist update
    G->>R: Enqueue job
    G-->>T: 2xx acknowledgement

    R->>W: Claim job
    W->>P: Load consent + profile
    W->>W: Determine allowed conversation path

    alt Astrology facts required
        W->>A: Deterministic calculation request
        A-->>W: Structured chart/transit facts
    end

    W->>S: Message + user context + ephemeral facts
    S-->>W: Draft Oria response
    W->>W: Policy/output validation
    W->>T: Send reply
    W->>P: Mark inbound event processed
    T-->>U: Oria reply
```

### Why explicit orchestration first

It guarantees that:

- chart facts exist before the LLM interprets them;
- the user cannot prompt the model into inventing missing chart calculations;
- birth-profile access remains inside application code;
- tool invocation is auditable;
- SecondContext does not need native MCP support for the first working version.

A later release can allow direct MCP tool calls from the LLM where appropriate, while retaining application-side authorization and schema validation.

---

## 19. Intent and calculation routing

The MVP does not need a complex autonomous agent loop.

A small router can classify each active message into categories such as:

- natal explanation;
- current transit interpretation;
- transit interpretation for a specified date;
- follow-up on previous interpretation;
- profile management;
- privacy/help;
- unsupported/high-stakes request.

The router can initially be rule-assisted plus a structured LLM classification call through the context/LLM layer. Tool execution remains application-controlled.

If a date is ambiguous, Oria asks the user to clarify rather than guessing.

---

## 20. Prompt and policy layers

The final model context should be assembled in a strict priority order.

```mermaid
flowchart TD
    P[Immutable product policy] --> M[Astrology methodology rules]
    M --> O[Oria persona]
    O --> C[Retrieved user conversational context]
    C --> A[Current calculated astrology facts]
    A --> U[Current user message]
    U --> L[LLM response generation]
    L --> V[Output policy validation]
    V --> S[Send response]
```

### 20.1 Product policy

Policy is not part of the persona and cannot be overridden by user messages or retrieved memory.

At minimum it states that Oria:

- identifies herself as an AI astrology personality when relevant and never claims to be human;
- does not present astrology as scientifically established fact;
- does not fabricate computed chart values;
- does not solicit PII outside the explicit onboarding/profile workflow;
- does not request legal name, phone number, email address, home address, employer, account identifiers, passwords, government IDs, payment details, or similar unrelated information;
- does not make deterministic high-impact predictions;
- does not provide medical diagnosis, legal advice, personalized investment instructions, or emergency guidance based on astrology;
- does not treat another person's private data as available merely because the current user mentions them;
- communicates uncertainty when birth time or calculation data is incomplete;
- obeys deletion and consent state before persona goals.

### 20.2 Astrology methodology

The methodology prompt separates:

- computed astronomical/astrological facts;
- traditional interpretation;
- conversational reflection.

The LLM must not infer an unprovided aspect solely because it would make a narrative fit.

### 20.3 Persona

Oria's persona can define:

- vocabulary;
- warmth;
- humor;
- level of mysticism;
- preferred answer structure;
- recurring stylistic motifs;
- how she handles uncertainty;
- how she asks follow-up questions that are not PII collection.

Persona iteration should not require changes to safety policy or domain code.

---

## 21. PII minimization

The MVP requirement is that Oria **never solicits unrelated PII**.

This should be enforced through multiple layers rather than only a system prompt:

1. onboarding is a deterministic state machine with a fixed list of allowed fields;
2. there is no generic “save arbitrary profile attribute” tool;
3. birth-profile repository APIs accept only the defined birth schema;
4. persona/system prompts explicitly prohibit other PII solicitation;
5. an output guard checks generated questions for common prohibited PII categories before sending;
6. tests include adversarial attempts to persuade Oria to request forbidden fields;
7. logs never contain raw birth-profile payloads;
8. profile data is not embedded into semantic/vector memory.

Users can still voluntarily type information that was not requested. When that happens, Oria should avoid repeating or soliciting more of it, and the system should avoid promoting obviously unnecessary sensitive values into structured long-term memory where practical.

---

## 22. Redis usage

Redis has three MVP responsibilities.

### 22.1 Job queue

Slow message processing happens in worker processes.

Jobs should carry identifiers, not decrypted PII. A job payload should normally contain an internal inbound-event ID that the worker uses to retrieve the required scoped state from PostgreSQL.

### 22.2 Per-user lock

Only one worker should mutate a user's conversation/profile state at a time.

A lock key can be scoped like:

`oria:user:<uuid>:conversation-lock`

The lock must have a bounded TTL and safe release semantics.

### 22.3 Temporary state/cache

Redis may contain short-lived:

- typing/debounce state;
- rate-limit counters;
- short calculation caches;
- ephemeral state-machine hints;
- queue metadata.

Anything required to recover the user's actual profile or consent state belongs in PostgreSQL.

---

## 23. PostgreSQL schema

Initial tables should include:

### `users`

Internal identity and lifecycle state.

### `social_identities`

Maps a channel identity to an internal user ID. Unique on `(provider, provider_user_id)`.

### `consents`

Versioned consent history.

### `birth_profiles`

Encrypted raw birth-profile payload plus schema/key versions.

### `onboarding_drafts`

Encrypted partial birth fields, normalized place candidates and callback revision
metadata. One row per user preserves deterministic onboarding across restarts;
confirmation replaces the draft with the strict final birth profile atomically.

### `astrology_profiles`

Derived natal calculation data and calculation provenance.

### `conversation_sessions`

Maps OriaEngine conversation state to the corresponding SecondContext session identifier.

### `inbound_events`

Durable Telegram update deduplication and processing status.

### `outbound_messages`

Optional but recommended record of attempted/sent replies for troubleshooting and duplicate reduction. Raw response text retention should follow the defined retention policy.

### `deletion_jobs`

Tracks multi-service deletion progress so `/delete-me` can be retried safely if one dependency is unavailable.

---

## 24. Idempotency and failure handling

Telegram and worker systems should be assumed to deliver work at least once.

Every inbound Telegram update has a provider update ID. Store it under a unique constraint. If the same update arrives again, acknowledge it without repeating the domain action.

Worker operations should use the inbound-event record as an idempotency anchor.

Important transitions should be durable:

- consent accepted;
- profile field updated;
- profile confirmed;
- natal calculation completed;
- deletion requested;
- deletion completed.

External calls should use bounded retries and timeouts.

A failed astrology calculation should not corrupt the profile. A failed LLM call should allow the event to retry. A failed Telegram send should be recorded and retried conservatively.

Exactly-once delivery of a Telegram message cannot be guaranteed across every crash boundary; the design should minimize duplicate replies and make duplicate state mutation impossible.

---

## 25. Privacy controls

### `/profile`

Shows the user the profile Oria is using:

- birth date;
- time and accuracy status;
- normalized birthplace;
- whether the natal chart is current;
- policy/consent version.

### `/edit-profile`

Starts the deterministic edit state machine. Updating any calculation-relevant field invalidates and recomputes derived natal data.

### `/privacy`

Explains:

- what data is collected;
- why it is collected;
- what is stored;
- how conversational context is used;
- how to edit/delete it;
- limitations of astrology and AI-generated interpretation.

### `/delete-me`

Requires a second explicit confirmation.

Deletion should remove or invalidate:

- encrypted birth profile;
- derived astrology profile;
- consent-linked application data as required by the retention policy;
- Telegram identity mapping when no longer needed;
- OriaEngine conversation records;
- SecondContext subject/session/memory data;
- Redis keys belonging to the user.

The deletion operation should be idempotent and tracked durably until all components report completion.

---

## 26. Safety boundaries for astrology advice

Oria may provide low-stakes reflective guidance, for example:

- themes to think about;
- journaling prompts;
- communication considerations;
- ways to frame a transition;
- traditional interpretations of a chart/transit;
- uncertainty-aware possibilities.

Oria should not use a chart to make authoritative claims about:

- disease or diagnosis;
- death or lifespan;
- pregnancy/fertility outcomes;
- accidents or disasters;
- criminality;
- whether another person is dangerous;
- certain relationship failure;
- certain financial gain/loss;
- personalized trades or financial transactions;
- legal outcomes.

When a user asks a high-stakes question, Oria can discuss the symbolic/reflective theme at a general level while explicitly declining to treat astrology as a reliable basis for the decision.

---

## 27. Observability

MVP observability should be useful without leaking private data.

### Structured logs

Log:

- request/update IDs;
- internal user UUID only where operationally necessary;
- job ID;
- state transition name;
- latency;
- downstream status;
- error category.

Do not log:

- bot token;
- raw birth profile;
- encryption keys;
- exact birth time/place;
- raw SecondContext auth tokens;
- entire user message text by default.

### Metrics

Useful initial metrics:

- Telegram updates received;
- updates deduplicated;
- queue depth and age;
- worker processing latency;
- failed jobs;
- consent acceptance rate;
- onboarding completion rate;
- astrology MCP latency/error rate;
- SecondContext latency/error rate;
- Telegram outbound latency/error rate;
- policy-blocked responses;
- delete workflow success/failure.

---

## 28. Configuration and secrets

Expected environment variables include:

```dotenv
APP_ENV=development
LOG_LEVEL=INFO

DATABASE_URL=postgresql+psycopg://oria:oria@postgres:5432/oria
REDIS_URL=redis://redis:6379/0

TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_BASE_URL=
TELEGRAM_WEBHOOK_SECRET=

PROFILE_ENCRYPTION_KEY=
PROFILE_ENCRYPTION_KEY_VERSION=v1

SECOND_CONTEXT_BASE_URL=http://secondcontext:8080
SECOND_CONTEXT_BEARER_TOKEN=

ASTROLOGY_MCP_URL=http://astrology-mcp:8000/mcp
ORIA_POLICY_VERSION=2026-09-28.1
```

Production secrets must come from the deployment platform's secret mechanism rather than committed files.

`.env` must be ignored by Git.

---

## 29. Local development workflows

The immediate delivery priority is a working demo. Implement the minimum needed
to connect the core flow, deferring optional polish without weakening consent,
privacy, or security requirements. The MVP completion criteria remain unchanged.

For the staged demo, consent acceptance starts or resumes deterministic onboarding.
Encrypted drafts preserve date/time progress and candidate selection; confirmed
profiles use the consent-checked storage repository. Live polling resolves local
places through `PlaceResolver`, clarifies clock changes, and saves confirmed profiles.
Calculation remains the next demo boundary (Stages 9–10).
Keep disclosure honest about unavailable saved-profile and
deletion controls, and bump the policy version for the collection disclosure.
All draft/profile writes check current consent under the user lock. Stage 10
activation must retain that check. See [onboarding](docs/onboarding.md),
[birth-profile storage](docs/birth-profiles.md) and [consent flow](docs/consent-flow.md).

The Makefile is the supported developer interface.

Expected commands:

| Command | Purpose |
|---|---|
| `make help` | Show documented targets |
| `make bootstrap` | Install local Python/dev dependencies |
| `make env` | Create `.env` from `.env.example` if absent |
| `make infra-up` | Start PostgreSQL and Redis |
| `make infra-down` | Stop local infrastructure |
| `make migrate` | Apply database migrations |
| `make api` | Run the HTTP gateway locally |
| `make mcp` | Run the astrology MCP service |
| `make run` | Run Telegram bot in local polling mode |
| `make worker` | Run worker process |
| `make dev` | Start the complete local Docker Compose development stack |
| `make logs` | Follow local service logs |
| `make format` | Format source |
| `make lint` | Run lint checks |
| `make typecheck` | Run static type checks |
| `make test-unit` | Run fast unit tests |
| `make test-integration` | Run dependency-backed integration tests |
| `make test-contract` | Verify service/API contracts |
| `make test-e2e` | Replay Telegram fixture conversations through the stack |
| `make test` | Run normal local test suite |
| `make verify` | Formatting check + lint + typecheck + all required CI tests |
| `make clean` | Remove generated local artifacts/caches |

No contributor should need to memorize underlying `uv`, `pytest`, Alembic, Docker Compose, Ruff, or type-checker commands for routine workflows.

---

## 30. Testing strategy

### Unit tests

Cover:

- consent state transitions;
- onboarding state transitions;
- date/time parsing;
- exact/approximate/unknown birth-time behavior;
- historical timezone conversion;
- birthplace disambiguation domain logic;
- encryption/decryption and key-version handling;
- user scoping;
- intent routing;
- PII solicitation guard;
- persona policy invariants;
- astrology fact formatting;
- idempotency helpers;
- lock semantics.

### Integration tests

Run against isolated PostgreSQL and Redis containers and verify:

- migrations from an empty database;
- social identity uniqueness;
- consent persistence;
- encrypted profile persistence;
- queue/worker execution;
- job retries;
- inbound update deduplication;
- user isolation;
- deletion workflow recovery.

### Astrology MCP contract tests

Use golden fixtures to verify that the calculation service returns stable structured results for known inputs.

The calculation engine version must be captured in each result so intentional algorithm/model changes can update fixtures explicitly.

### SecondContext contract tests

Verify:

- required auth behavior;
- correct subject scoping;
- session creation/reuse;
- response parsing;
- failure behavior;
- deletion capability once implemented.

### Telegram replay E2E tests

Store sanitized Telegram update fixtures and replay flows such as:

1. `/start` → consent decline;
2. `/start` → consent accept → full profile → first reading;
3. unknown birth time → answer that avoids houses/ascendant;
4. ambiguous city → location selection;
5. duplicate update → exactly one state mutation;
6. profile edit → chart invalidation/recompute;
7. high-stakes request → policy-bounded response;
8. attempt to make Oria request email/phone/address → blocked;
9. `/delete-me` → complete multi-service deletion.

### Live Telegram smoke test

A manual/optional target may use a dedicated development bot token. It must never be required in CI.

---

## 31. CI expectations

The required CI command should be:

```bash
make verify
```

CI should fail on:

- formatting drift;
- lint errors;
- type-check errors;
- unit-test failure;
- migration failure;
- integration-test failure;
- contract-test failure;
- privacy/policy invariant failure.

A GitHub Actions workflow can install Docker Compose and uv, then invoke the Make target so CI behavior matches local verification.

---

## 32. Deployment model

A minimal deployment contains:

```mermaid
flowchart LR
    I[Internet] --> RP[HTTPS Reverse Proxy]
    RP --> G[OriaEngine Gateway]

    G --> PG[(PostgreSQL)]
    G --> R[(Redis)]
    R --> W1[Worker]
    R --> W2[Worker]

    W1 --> A[Astrology MCP]
    W2 --> A
    W1 --> S[SecondContext]
    W2 --> S

    A --> AM[Astrology model]
```

Only the HTTPS gateway needs to be reachable by Telegram. PostgreSQL, Redis, workers, Astrology MCP, and SecondContext should remain on private networks.

For a first personal deployment, Docker Compose on a single host is acceptable. The architecture should not require Kubernetes.

---

## 33. Security baseline

Before public testing:

- Telegram webhook secret validation is enabled;
- bot token never appears in logs;
- all SQL queries are user-scoped through repositories;
- profile encryption is enabled outside unit tests;
- database backups are encrypted;
- no raw PII is included in metrics;
- service-to-service timeouts are configured;
- rate limits exist per Telegram user/chat;
- inbound message size is bounded;
- unsupported Telegram update types are ignored;
- admin/debug endpoints are disabled or authenticated in production;
- deletion has been exercised end-to-end;
- restore behavior has been tested for PostgreSQL;
- Redis loss has been tested and does not destroy canonical state.

---

## 34. MVP completion criteria

The MVP is complete when all of the following are true:

1. A new Telegram user can start a private chat.
2. Birth data cannot be collected into the profile before explicit consent.
3. The full profile flow works with exact, approximate, and unknown birth times.
4. Birthplace resolution produces stable coordinates/timezone without LLM inference.
5. Birth profile is encrypted at rest at the application layer.
6. The astrology MCP container produces a natal chart from normalized inputs.
7. Oria can answer a chart question using structured calculated facts.
8. Oria can answer a current/date-specific transit question using calculated facts.
9. Oria does not fabricate unavailable houses/ascendant information.
10. SecondContext gives continuity across separate Telegram conversations.
11. Raw birth profile fields are not written into general semantic memory by OriaEngine.
12. Duplicate Telegram updates do not repeat state mutations.
13. Two simultaneous messages from one user are serialized safely.
14. Different users cannot access one another's profile/context.
15. `/profile` and `/edit-profile` work.
16. `/privacy` accurately describes the implementation.
17. `/delete-me` purges the user across OriaEngine and SecondContext.
18. Policy tests demonstrate that Oria does not solicit common unrelated PII categories.
19. High-stakes astrology requests receive bounded, non-deterministic responses.
20. `make verify` passes from a clean checkout with the documented prerequisites.

---

## 35. Post-MVP directions

After v0.1 validates the interaction model, possible extensions include:

- Instagram Professional-account DM adapter;
- Matrix adapter;
- Discord adapter;
- scheduled opt-in daily/weekly readings;
- controlled outbound messages with explicit notification consent;
- richer astrology MCP feature families;
- relationship/synastry mode with a separate consent/privacy model;
- user-selectable Oria tone/intensity;
- structured feedback on whether interpretations were useful;
- prospective prediction experiments with locked timestamps and proper baselines;
- experimental statistical models that test whether astrological features add predictive value beyond non-astrological baselines;
- social posting/content generation as a separate channel from private DM conversations.

Predictive experimentation should remain separate from the user-facing interpretive product. If implemented, it should use prospective evaluation, negative examples, held-out data, timestamped predictions, and calibration metrics rather than retrospective narrative fitting.

---

## 36. Design principles summary

OriaEngine should remain guided by a small number of durable principles:

> **A person-like experience, not a person-like security model.**

Oria can have personality and continuity, but permissions, data collection, consent, and deletion are deterministic application responsibilities.

> **Calculate first, interpret second.**

The astrology service produces facts. The LLM explains them.

> **Collect less.**

The system should know the user's chart without trying to know their identity.

> **PostgreSQL remembers; Redis coordinates.**

Canonical state survives worker and cache failure.

> **Policy outranks persona.**

Oria's character can evolve without weakening privacy or safety boundaries.

> **Telegram is the first adapter, not the product architecture.**

The core should remain reusable for future social and messaging channels.
