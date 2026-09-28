# Deterministic onboarding

`domain.onboarding.OnboardingFlow` handles the fixed birth fields after
`ConsentFlow` resolves the sender and current consent. It uses no LLM, Redis,
external geocoder or Telegram types. One transaction holds the user row lock
through consent checks, draft changes and final profile confirmation; replies
are sent after commit. Missing/deleted users and withdrawn/stale consent cannot
write drafts or profiles.

## States and inputs

| State | Accepted input / next step |
| --- | --- |
| `ConsentRequired` / `Closed` | Existing explicit consent flow |
| `BirthDateRequired` | `YYYY-MM-DD` or English `DD Mon YYYY`, such as `13 Apr 1990` |
| `BirthTimeRequired` | 24-hour `HH:MM` (exact), `exact HH:MM`, `approximate HH:MM`, or `unknown` / Unknown button |
| `BirthPlaceRequired` | `city, country` only; deterministic resolver returns candidates |
| `BirthPlaceConfirmation` | Select a candidate, or request another city |
| `BirthTimeClarification` | Select an occurrence of a repeated time, correct a gap, or choose unknown |
| `ProfileConfirmation` | Review summary; confirm or edit date, time or place |
| `ComputingProfile` | Confirmed encrypted profile awaits successful calculation |
| `Active` | Valid derived result cached; interpretation arrives in later stages |

Numeric slash dates, impossible/future dates, offsets, informal time phrases and
extra text are rejected with a focused retry. Unknown time stores no invented
time. Place queries accept two bounded name components; addresses, numbers and
additional comma-separated fields are rejected. Queries are not stored. Only
normalized resolver candidates can become a selected place. The parser is not a
general detector of unsolicited PII: it accepts constrained names, never arbitrary
profile attributes. Both draft and final schemas forbid extra keys.

The resolver derives state from draft completeness, with consent taking priority.
`/start` resumes without resetting fields; `/help`, `/privacy`, unknown commands
and stale callbacks do not become birth input. Editing clears only the selected
field and invalidates any time-occurrence selection. Confirmation creates the strict
`BirthProfilePayload` through the existing
consent-checked repository and removes the draft atomically. A confirmed profile
calls MCP and becomes active only on success. Failed calculation
retains the encrypted profile for retry. Saved-profile editing reuses these editors;
/profile reports calculation status. Full profile display and deletion remain later
stages. See [derived profiles](astrology-profiles.md).

## Durable progress and privacy

Migration `0004` adds one `onboarding_drafts` row per owner, containing ciphertext,
schema/key versions and an update timestamp. The encrypted version 1 draft holds
only the permitted birth fields, up to eight normalized candidates, consent UUID
and a random callback revision token, plus an optional time-occurrence selection.
Older drafts without the optional field still load. No raw message or unresolved
query is saved.
Progress survives process/Redis loss; no process-local state is authoritative.
Downgrading `0004` removes drafts while retaining confirmed profiles and consent.

Draft encryption uses the same configured AES-256-GCM key and fresh 12-byte nonce
per write as [birth profiles](birth-profiles.md), with a separate AAD domain:
`["oria:onboarding-draft:aes256gcm:v1", owner_uuid, 1, key_version]` encoded as compact
JSON. Moving ciphertext between users or between draft/final-profile contexts
fails authentication. Drafts and replies redact sensitive repr output. Never log
serialized models, individual fields, validation error dictionaries or SQL errors.

Buttons contain only a random token and bounded action/index, not birth values
or owner IDs. Every mutation rotates the token. Re-consent also rotates it;
callbacks from earlier revisions/users cannot select or confirm another draft.
Decline retains encrypted progress and stops processing; this is not deletion.
Same-policy consent-button replay and durable text-update deduplication remain
Stage 11. No exactly-once Telegram delivery is claimed.

## Local demo

`domain.places.PlaceResolver` is the local async interface for city/country lookup.
Polling uses `LocalPlaceResolver` with bundled GeoNames data and historical
timezone rules. See [place resolution](place-resolution.md) for coverage, time
clarification and dataset generation. Confirmed profiles calculate through MCP.
Start `make mcp-local` for host polling.

Before `make run`, apply `make migrate`, retain a stable `PROFILE_ENCRYPTION_KEY`,
and set `ORIA_POLICY_VERSION=2026-09-28.2` in the ignored local `.env`. Polling rejects
the previous defaults `2026-09-01`, `2026-09-28` and `2026-09-28.1`. Operators using
custom policy versions must also bump their version for the calculation disclosure. No local secrets
or developer database are modified by implementation tests.

`make verify` tests date/time modes and rejection, schema restrictions, encryption
context/tampering, full confirmation, edits, restart recovery, isolation, stale
buttons, consent changes, withdrawal ordering, concurrent confirmation, migration
round trips and metadata drift. Telegram delivery is mocked; live smoke checks
remain an operator task in [Telegram setup](telegram.md).
