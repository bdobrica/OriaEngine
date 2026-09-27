# Configuration and HTTP skeleton

Run `make bootstrap`, optionally `make env`, then `make api`. The local gateway
listens on `http://127.0.0.1:8001` (port 8000 remains available for Astrology MCP).
Stop it with Ctrl-C or SIGTERM; Uvicorn drains requests and the FastAPI lifespan
closes registered resources in reverse order through `app.state.resources`.
Uvicorn is a direct runtime dependency because it serves this entrypoint.

## Configuration

`oria_engine.config.Settings` reads case-insensitive environment variables and an
optional `.env` in the current directory. Environment variables override `.env`.
Unknown dotenv entries are ignored. Production secrets come from the deployment
platform; do not deploy a development `.env` or commit secrets.

| Variable | Default / validation |
| --- | --- |
| `APP_ENV` | `development`; accepts `development`, `test`, `production` |
| `LOG_LEVEL` | `INFO`; accepts `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `DATABASE_URL` | Local PostgreSQL URL from `.env.example`; `postgresql+psycopg`, host and database required |
| `REDIS_URL` | `redis://localhost:6379/0`; `redis` or `rediss`, host required |
| `TELEGRAM_BOT_TOKEN` | Empty locally; numeric bot ID followed by `:` and URL-safe token characters |
| `TELEGRAM_WEBHOOK_BASE_URL` | Empty locally; HTTPS URL when supplied |
| `TELEGRAM_WEBHOOK_SECRET` | Empty locally; 1–256 alphanumeric, `_` or `-` characters when supplied |
| `PROFILE_ENCRYPTION_KEY` | Empty locally; base64 (standard or URL-safe, padded) encoding of 32 random bytes for AES-256 |
| `PROFILE_ENCRYPTION_KEY_VERSION` | `v1`; nonempty version identifier |
| `SECOND_CONTEXT_BASE_URL` | `http://localhost:8080`; HTTP(S) |
| `SECOND_CONTEXT_BEARER_TOKEN` | Empty; optional bearer authentication |
| `ASTROLOGY_MCP_URL` | `http://localhost:8000/mcp`; HTTP(S) |
| `ORIA_POLICY_VERSION` | `2026-09-01`; nonempty version identifier |

HTTP URLs reject embedded credentials, query strings and fragments. Authentication
belongs in the dedicated secret settings. Version identifiers use letters, digits,
`.`, `_`, and `-`, start with a letter/digit and are at most 64 characters long.

Production requires explicit database, Redis, SecondContext and Astrology MCP URLs,
a nonempty bot token, HTTPS webhook base URL, webhook secret and encryption key.
SecondContext authentication remains optional, as specified in the plan. Supplied
values are validated in every environment. These are syntax/presence checks, not
credential verification or a production deployment readiness guarantee.
The process fails before opening a listener on invalid configuration and emits a
generic diagnostic without raw settings or validation input. Never log Pydantic
validation error dictionaries, which can include inputs.

## HTTP contract

| Endpoint | Response |
| --- | --- |
| `GET /healthz` | 200, `{"status":"ok"}`; process liveness only |
| `GET /readyz` | 200, `{"status":"ready","checks":{}}` when lifespan has started and all registered checks succeed |
| `GET /readyz` | 503, `{"status":"not_ready","checks":{"storage":false}}` for a failed registered check (example name), or when lifespan is inactive |

Register named async checks with `create_app(readiness_checks={...})`. Checks run
concurrently, each with a two-second timeout, and return booleans. Errors and
timeouts become `false`; exception details never enter responses. Check names are
static application identifiers, never user inputs. Stage 1 registers no external
checks: readiness currently means the skeleton has started, not that PostgreSQL,
Redis or downstream services are reachable. Their owning integration stages add
the checks and lifecycle resources. Cancellation propagates on shutdown.

Responses carry a generated UUID-based `X-Request-ID`; caller-provided IDs are not
trusted or echoed. The same ID appears in request logs. Future Telegram handlers
can use `correlation_scope(telegram_update_id=...)` around a normalized update.
Context is isolated across concurrent tasks and restored after each scope.
OpenAPI at `/openapi.json` describes both endpoints in development/test; API docs
and OpenAPI routes are disabled in production.

## Logging privacy rule

Raw birth-profile payloads, exact birth date/time/place, user message text,
credentials and encryption keys are never logged. Do not pass these values to a
logger, even at DEBUG. Do not log request bodies, headers, URLs or query strings.

The JSON formatter emits only timestamp, level, a known static event,
correlation/update IDs, and numeric status/latency fields. Unknown messages
(including third-party library messages) become `log_record`; arbitrary extras,
format arguments, traceback/exception strings and stack text are discarded.
This deliberately limits third-party diagnostics until safe event adapters exist.
Configured secret values and database/Redis passwords are also redacted as defense
in depth. Redaction is not a way to make arbitrary profile text safe to log.

The supported entrypoint configures application and Uvicorn logging together and
disables Uvicorn access logs. Custom launchers must retain that configuration;
adding independent handlers or log sinks can bypass the privacy boundary.
