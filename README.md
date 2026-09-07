# OriaEngine

**OriaEngine** is the application runtime for **Oria**, a persistent AI astrology personality designed to interact with users through private messaging.

The first MVP targets **Telegram**. A user can talk to Oria in a DM, explicitly consent to providing the minimum birth information required for astrological calculations, create a persistent birth profile, and receive personalized interpretations grounded in deterministic chart calculations and prior conversation context.

OriaEngine is designed to build on [SecondContext](https://github.com/bdobrica/SecondContext) for persistent conversational memory while keeping private birth-profile data in a separate, encrypted application store.

> **Project status:** design / early MVP implementation.
>
> Astrology is used here as an interpretive framework. Oria should not be treated as a source of scientific prediction, medical advice, legal advice, financial advice, or other high-stakes professional guidance.

## What the MVP does

- interacts with users in private Telegram chats;
- presents a versioned disclosure and requires explicit consent before collecting birth data;
- collects only the calculation profile: birth date, birth time/accuracy, and birthplace;
- supports exact, approximate, and unknown birth times;
- resolves birthplace, coordinates, timezone, and historical UTC birth instant deterministically;
- stores raw birth-profile data encrypted in PostgreSQL;
- runs the astrology mathematical model as a separate FastMCP service;
- computes and stores a derived natal profile;
- calculates transits/aspects when needed for a conversation;
- uses SecondContext for persistent conversational context and preferences;
- keeps calculated facts separate from LLM interpretation;
- prevents the personality layer from overriding privacy and safety policy;
- uses Redis for worker jobs, per-user locks, and temporary state;
- supports profile inspection, correction, privacy information, and deletion.

## Architecture

```mermaid
flowchart TD
    U[Telegram user] --> TG[Telegram Bot API]
    TG --> G[OriaEngine gateway<br/>Python / FastAPI / aiogram]

    G --> PG[(PostgreSQL<br/>canonical app state)]
    G --> R[(Redis<br/>queue / locks / temporary state)]
    R --> W[OriaEngine worker]

    W --> PG
    W --> SC[SecondContext<br/>conversation memory]
    W --> MCP[Astrology MCP<br/>FastMCP]
    MCP --> M[Mathematical astrology model]

    W --> TG
```

The main architectural rules are:

- **PostgreSQL is the source of truth.**
- **Redis is disposable coordination state.**
- **Birth data is private profile data, not semantic memory.**
- **The astrology service calculates; the LLM interprets.**
- **Policy outranks persona.**
- **Telegram is an adapter, so other messaging networks can be added later.**

See [PLAN.md](PLAN.md) for the complete design.

## Oria's behavior

Oria is intended to feel like a consistent astrology personality rather than a generic assistant. She can remember conversational preferences and prior discussions, explain natal placements, interpret current or date-specific transits, and offer low-stakes reflective suggestions.

Oria must remain transparent about being an AI personality and must never fabricate chart facts.

The response model separates:

1. deterministic computed facts;
2. traditional astrological interpretation;
3. reflective conversational advice.

If data is unavailable — for example because the user's birth time is unknown — Oria should say so rather than inventing an ascendant or house placement.

## Privacy model

The MVP intentionally keeps the user profile small.

Oria may solicit only the information required to calculate the profile:

- birth date;
- birth time, including an “unknown” option;
- birthplace, normally city + country, plus clarification needed to disambiguate the place.

The system should not solicit unrelated data such as legal name, email address, phone number, home address, employer, government identifiers, passwords, or payment details.

Raw birth-profile data is stored in PostgreSQL using application-level authenticated encryption. It is not intentionally stored as a SecondContext semantic memory or vector embedding.

The Telegram identity mapping stores only the identifiers required to route messages. Display names, usernames, phone numbers, and profile metadata are not copied into the Oria profile by default.

Users will have:

- `/profile` — inspect the profile used for calculations;
- `/edit-profile` — correct birth information;
- `/privacy` — see what is collected and why;
- `/delete-me` — request complete profile/context deletion.

## Safety boundaries

Oria can discuss symbolic themes and low-stakes reflection, but astrology must not be presented as a reliable basis for high-impact decisions.

The MVP explicitly avoids deterministic predictions about illness, death, pregnancy, accidents, criminal behavior, financial ruin, or certain relationship outcomes. It also avoids medical diagnosis, personalized investment instructions, legal advice, and similar high-stakes guidance based on astrology.

## Planned stack

- Python 3.12+
- FastAPI
- aiogram 3
- PostgreSQL
- SQLAlchemy 2.x + Alembic
- Redis
- Dramatiq with Redis broker
- FastMCP
- SecondContext
- Pydantic
- httpx
- cryptography
- pytest
- Ruff
- mypy/Pyright
- Docker Compose
- uv
- Make

## Repository structure

The implementation is organized around application responsibilities:

- `src/oria_engine/domain/` — consent, onboarding, profile, policy, conversation logic;
- `src/oria_engine/telegram/` — Telegram transport adapter;
- `src/oria_engine/db/` — SQLAlchemy models and repositories;
- `src/oria_engine/queue/` — Redis/Dramatiq workers and user locks;
- `src/oria_engine/context/` — SecondContext adapter;
- `src/oria_engine/astrology/` — MCP client and calculation contracts;
- `src/oria_engine/persona/` — Oria persona and prompt assembly;
- `src/oria_engine/privacy/` — encryption, redaction, deletion;
- `services/astrology_mcp/` — Dockerized FastMCP wrapper for the mathematical model;
- `migrations/` — Alembic migrations;
- `tests/` — unit, integration, contract, and E2E tests;
- `deploy/` — local/deployment configuration.

The implementation order is tracked in [TODO.md](TODO.md).

## Prerequisites

For local development, install:

- Git;
- Docker with Docker Compose v2;
- GNU Make;
- Python 3.12+;
- [uv](https://docs.astral.sh/uv/);
- a Telegram bot token from BotFather for live local testing;
- access to a SecondContext instance for full conversational integration.

CI and most automated tests do **not** require a real Telegram bot token.

## Install

Clone the repository and bootstrap the development environment:

```bash
git clone https://github.com/<your-user>/OriaEngine.git
cd OriaEngine
make bootstrap
make env
```

`make env` creates `.env` from `.env.example` when one does not already exist. Add local secrets to `.env`; never commit it.

Start PostgreSQL and Redis and apply migrations:

```bash
make infra-up
make migrate
```

## Configuration

The initial configuration surface is expected to include:

```dotenv
APP_ENV=development
LOG_LEVEL=INFO

DATABASE_URL=postgresql+psycopg://oria:oria@localhost:5432/oria
REDIS_URL=redis://localhost:6379/0

TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_BASE_URL=
TELEGRAM_WEBHOOK_SECRET=

PROFILE_ENCRYPTION_KEY=
PROFILE_ENCRYPTION_KEY_VERSION=v1

SECOND_CONTEXT_BASE_URL=http://localhost:8080
SECOND_CONTEXT_BEARER_TOKEN=

ASTROLOGY_MCP_URL=http://localhost:8000/mcp
ORIA_POLICY_VERSION=2026-09-01
```

Use a generated development key for `PROFILE_ENCRYPTION_KEY`. Production deployments must provide secrets through the deployment platform rather than a committed environment file.

## Run locally

### Full local Docker development stack

When the Docker development stack is implemented:

```bash
make dev
```

This starts the OriaEngine-owned services: gateway, worker, PostgreSQL, Redis, and Astrology MCP. SecondContext can be configured as an external service through `SECOND_CONTEXT_BASE_URL`.

Follow logs with:

```bash
make logs
```

Stop the stack with:

```bash
make down
```

### Telegram polling mode

For development, OriaEngine supports Telegram long polling so no public HTTPS endpoint is required:

```bash
make run
```

Run the worker in another terminal when it is not already running through Docker Compose:

```bash
make worker
```

Run the astrology MCP service separately when needed:

```bash
make mcp
```

Production deployments use Telegram webhooks instead of polling.

## Makefile workflows

The Makefile is the supported interface for common development tasks.

```bash
make help
make bootstrap
make env
make infra-up
make migrate
make api
make run
make worker
make mcp
make dev
make logs
make format
make lint
make typecheck
make test-unit
make test-integration
make test-contract
make test-e2e
make test
make verify
make down
make clean
```

The exact commands behind these targets may evolve; contributor-facing workflows should remain stable where practical.

## Testing

### Fast tests

```bash
make test-unit
```

Unit tests cover domain logic such as consent, onboarding, parsing, encryption, profile scoping, policy rules, and calculation routing.

### Integration tests

```bash
make test-integration
```

Integration tests start isolated PostgreSQL and Redis dependencies and validate migrations, repositories, queue behavior, retries, idempotency, user isolation, and deletion recovery.

### Contract tests

```bash
make test-contract
```

Contract tests validate the structured interfaces to Astrology MCP and SecondContext. Astrology calculations use golden fixtures so deliberate model changes are visible in review.

### End-to-end replay tests

```bash
make test-e2e
```

E2E tests replay sanitized Telegram update fixtures without requiring a real Telegram account. They cover the consent flow, onboarding, profile editing, chart calculation, safety behavior, duplicate updates, and deletion.

### Full verification

Before opening a pull request:

```bash
make verify
```

`make verify` is intended to be the same command required by CI and includes formatting verification, linting, type checking, and all mandatory test lanes.

## Telegram deployment model

Local development uses long polling. Production uses a webhook exposed through HTTPS.

```mermaid
sequenceDiagram
    participant U as Telegram user
    participant T as Telegram
    participant G as OriaEngine gateway
    participant R as Redis
    participant W as Worker

    U->>T: Send private message
    T->>G: HTTPS webhook update
    G->>G: Validate webhook secret
    G->>G: Persist / deduplicate update
    G->>R: Enqueue inbound event ID
    G-->>T: 2xx
    R->>W: Process job
    W->>T: Send Oria response
    T-->>U: Deliver response
```

Only the public gateway needs internet ingress. PostgreSQL, Redis, workers, Astrology MCP, and SecondContext should remain private services.

## Development principles

### Calculate first, interpret second

Planetary positions, aspects, houses, transits, orbs, and other mathematical values must come from the calculation service. The LLM should explain supplied values, not invent them.

### Collect less

Oria should know what is necessary to calculate a chart without trying to build a broad identity profile of the person behind it.

### Policy outranks persona

Oria's tone and character can evolve. Consent, data access, PII rules, deletion, and high-stakes boundaries are application policy and cannot be overridden by personality prompts.

### Postgres remembers; Redis coordinates

Loss of Redis should never destroy the user's canonical consent or profile state.

### Telegram is an adapter

The first MVP is a Telegram bot, but the domain model is intentionally transport-neutral so Instagram, Matrix, Discord, or other channels can be added later.

## Roadmap

After the Telegram MVP is stable, likely directions include:

- Instagram DM support;
- opt-in daily or weekly readings;
- additional astrology calculations;
- richer feedback/evaluation;
- additional social/messaging adapters;
- carefully separated prospective research into whether astrological feature sets add predictive value beyond ordinary contextual baselines.

See [TODO.md](TODO.md) for the consecutive MVP implementation checklist and [PLAN.md](PLAN.md) for the detailed product and architecture design.

## References

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [aiogram](https://docs.aiogram.dev/)
- [FastMCP](https://gofastmcp.com/)
- [SecondContext](https://github.com/bdobrica/SecondContext)
