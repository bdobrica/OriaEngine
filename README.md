# OriaEngine

OriaEngine runs **Oria**, an AI astrology personality for private Telegram chats.
Users explicitly consent, create an encrypted birth profile, and receive
interpretations of deterministic natal and transit calculations with conversational
continuity through [SecondContext](https://github.com/bdobrica/SecondContext).

**Status:** the demo pipeline, privacy commands, deletion, webhook ingress and
Docker development stack are implemented. The [Stage 25 release gate](TODO.md#stage-25--mvp-release-gate)
is still pending; the project is not MVP-complete.

Astrology is an interpretive framework, not a scientifically established forecasting
method. Oria is not a source of medical, legal, financial or other high-stakes advice.

## Quick start: verify a checkout

Install Git, GNU Make, Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker and
Docker Compose v2. Use a POSIX shell (for example, Linux/WSL). The locked
`pyswisseph` source build needs C/C++ compilers, libc development headers and
headers for your Python interpreter. Docker must be running and accessible to
your user. An uncached bootstrap/build needs network access to package and image registries.

```sh
git clone https://github.com/bdobrica/OriaEngine.git
cd OriaEngine
make bootstrap
make test-unit
make verify
```

No `.env`, Telegram token, OpenAI key, live SecondContext service or sibling checkout
is needed for these tests. `make verify` checks formatting, lint and strict mypy,
then runs unit, integration, contract and E2E lanes. Tests start and remove isolated
Docker services with generated credentials; they do not use your local database.
See [testing](docs/testing.md) for coverage and limits. `make help` lists all targets.

## Run a Telegram demo

1. Run `make env` to create the ignored `.env` without replacing an existing one.
2. [Create a development bot with BotFather](docs/telegram.md) and set its token.
3. [Generate and retain an encryption key](docs/birth-profiles.md#encryption-and-keys),
   replace the PostgreSQL password placeholder and match the host `DATABASE_URL`.
4. Start a compatible, separately managed [SecondContext service](docs/second-context.md).
   Configure its URL, service authentication and subject namespace for chat and deletion.
   Its OpenAI credentials belong in SecondContext, not OriaEngine.
5. Set `SECOND_CONTEXT_DOCKER_URL` to an address reachable from containers and retain
   `ORIA_POLICY_VERSION=2026-10-03.2`. For polling, leave the webhook secret empty
   and use a development bot with no registered webhook.

```sh
make dev
make run
```

`make dev` builds gateway/worker/MCP images, starts PostgreSQL/Redis, applies
migrations and waits for container health. `make run` polls on the host and feeds
the container worker. Send `/start`, accept the disclosure, complete the prompted
profile, then ask `Explain my natal chart` or `transits today`.

Use `make logs` for container logs, `make metrics` for private aggregate status,
and `make down` to stop the stack while preserving PostgreSQL data. Stop polling
with Ctrl-C. See [Docker development](docs/development.md) for networking and mode
switching, [host polling](docs/telegram.md) for the host-worker alternative, and
[webhook setup](docs/telegram-webhook.md) for explicit HTTPS registration.

## Core boundaries

- PostgreSQL owns identity, consent, encrypted profiles and canonical jobs;
  Redis coordinates UUID-only work and can be rebuilt.
- Swiss Ephemeris plus Oria's astrology calculation engine produces structured
  facts through a private MCP service. The LLM interprets them.
- Consent, onboarding, profile edits and deletion use deterministic application
  code. Policy takes priority over persona.
- Raw birth fields stay out of SecondContext requests and explicit semantic memory.
  Filtered active messages and generated replies can be retained by SecondContext
  and its AI provider; filtering has documented limits.

Commands include `/profile`, `/edit_profile`, `/retry_profile`, `/privacy` and
`/delete_me`. Decline stops processing but retains previous data; deletion requires
confirmation and durable cleanup across services. See [profile commands](docs/profile-commands.md)
and [deletion and retention](docs/deletion.md).

## Documentation

| Topic | Reference |
| --- | --- |
| Component ownership and message flow | [Architecture](docs/architecture.md) |
| Typed settings and Compose variables | [Configuration](docs/application.md#configuration) |
| Storage, migrations and key management | [Database](docs/database.md), [encrypted profiles](docs/birth-profiles.md) |
| BotFather, polling and HTTPS ingress | [Telegram](docs/telegram.md), [webhooks](docs/telegram-webhook.md) |
| Calculation contracts and development | [Astrology MCP](docs/astrology-mcp.md) |
| Versioned container images and Quay setup | [Image publishing](docs/image-publishing.md) |
| Conversation dependency and policy | [SecondContext](docs/second-context.md), [worker pipeline](docs/conversation-worker.md) |
| Logs, health, limits and recovery | [Operations](docs/operations.md), [abuse controls](docs/abuse-controls.md) |
| Known gaps and live checks | [MVP limitations](docs/limitations.md) |
| Implementation intent and remaining release work | [PLAN.md](PLAN.md), [TODO.md](TODO.md) |

Durable validation records live in [docs/evidence](docs/evidence).
