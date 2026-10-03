# Derived astrology profiles

After explicit confirmation, OriaEngine saves the encrypted birth profile and calls
`calculate_natal_chart` through `AstrologyClient` / `FastMCPAstrologyClient`. The
request contains only calculation inputs from the [v1 contract](astrology-mcp.md),
never identity or place names. UTC conversion uses bundled historical rules.
Legacy unresolved clock-change times return to clarification and confirmation.

Migration `0005` adds one private `astrology_profiles` JSONB row per owner. It stores
validated structured facts, calculation timestamp, source profile UUID, source
schema version and source update timestamp. That tuple identifies the source
revision without storing a guessable hash of raw birth values. Calculation versions
include engine, binding, ephemeris/backend/data, wire contract, options, timezone
release and bundled dataset hashes. Raw birth date/time/place and UTC input are not
copied into the cache. JSONB chart facts are private but not application-encrypted;
restrict database access and protect backups. Birth payload encryption is unchanged.

A profile is `Active` only when current consent, no unfinished draft, source revision,
calculation versions and validated cached result all agree. There is no independent
active flag that can outlive those checks. Unknown-time success records explicit
unavailability; it does not imply a complete chart exists. Approximate-time and
unsupported-house limitations remain visible. Derived data is disposable: deleting
it or upgrading calculation versions requires recomputation from canonical inputs.

/profile reads status without MCP calls. /retry_profile computes missing or stale
results; a valid cache is reused. /edit_profile opens the existing field editors and
immediately invalidates the cache, even before final confirmation. Confirming edits
replaces the encrypted source and recomputes. Repository-level source writes and
draft writes also invalidate the cache. Telegram command names use underscores;
[profile inspection](profile-commands.md) also displays birth details and consent;
deletion remains Stage 18.

Calculation is bounded to 20 seconds and runs under the existing per-user database
lock inside the conversation worker. Consent withdrawal and profile edits serialize with
activation; unrelated users have independent locks. A failed tool call, invalid
response or timeout leaves the confirmed profile recoverable, with a generic retry
message and no partial result. A failed refresh preserves the older cache row but
its stale versions prevent use. Process cancellation rolls the transaction back;
previously committed encrypted progress remains recoverable. The [worker queue](worker-queue.md) commits domain changes with an encrypted reply
and deduplicates update processing; Telegram delivery can still duplicate after a crash.

## Local demo

1. Apply `make migrate` (current head `0007`).
2. Run `make mcp-local` to opt into a loopback-only port for host polling. The default
   `make mcp` retains the private-network deployment with no published port. The
   polling override adds a bridge network because Docker cannot publish ports on
   an internal-only network; this local mode therefore also permits outbound traffic.
3. Use `ASTROLOGY_MCP_URL=http://localhost:8000/mcp` and
   `ORIA_POLICY_VERSION=2026-10-03.1` in your local configuration. Bump custom policy
   versions too: the disclosure now includes conversation processing and storage.
4. Run `make worker` and `make run` in separate terminals, accept the current disclosure, and confirm the profile. Previously
   confirmed profiles use /retry_profile after consent. /profile reports validity.

`ASTROLOGY_MCP_PORT` overrides the local published port; update the URL to match.
Do not expose this unauthenticated service publicly. Downgrading `0005` removes only
derived caches, retaining encrypted birth profiles and drafts. Re-upgrading allows
recomputation. Active profiles now support [transit fact replies](transits-and-routing.md).
The [conversation worker](conversation-worker.md) connects LLM interpretation;
complete deletion remains Stage 18.
