# Encrypted birth profiles

`domain.birth_profile.BirthProfilePayload` is the version 1 internal storage
schema. It accepts only birth date, optional offset-free local time, time accuracy
(`exact`, `approximate`, `unknown`), and a normalized birthplace. Known accuracy
requires a time; unknown requires no time. Place fields are display name, city,
optional region, two-letter uppercase country code, bounded latitude/longitude,
and a recognized IANA timezone. Unknown fields are rejected at both levels.
The schema checks shape, not whether a city matches coordinates or a country;
the deterministic place resolver owns that responsibility in Stage 8. Historical
time conversion, date-entry parsing and onboarding remain subsequent stages.

Apply migration `0003` with `make migrate`. `birth_profiles` has one row per user:
UUID, owner UUID, encrypted payload, schema/key versions, and creation/update
timestamps. No birth fields or plaintext hashes are stored in separate columns.
Downgrading this revision deletes all birth profiles but retains identity/consent.
Calculation version and activation belong to the derived chart stage, not this row.

## Encryption and keys

`privacy.encryption.ProfileEncryption(settings)` requires a configured
`PROFILE_ENCRYPTION_KEY` in every environment where profile storage is used.
It uses the existing `cryptography` dependency and AES-256-GCM with a fresh
cryptographically random 12-byte nonce per encryption, including updates.
Envelope v1 is `nonce || ciphertext || 16-byte authentication tag`.
Associated data is the compact JSON array of domain/envelope identifier
`oria:birth-profile:aes256gcm:v1`, owner UUID, profile UUID, integer schema version,
and key version. Moving ciphertext between owners/profiles or modifying the
authenticated metadata fails decryption. This follows the
[cryptography AESGCM API](https://cryptography.io/en/latest/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM).
Authenticated encryption does not detect replay of an older valid envelope for
the same row; database access controls and backups remain operational concerns.

Provide a base64-encoded 32-byte random key through runtime secret configuration;
keep it out of source, logs, database rows, and chat. For local development, store
it in the ignored `.env` through your local secret workflow. Keep a secure backup:
losing the key loses access to profiles. Do not regenerate it on process startup.
`PROFILE_ENCRYPTION_KEY_VERSION` identifies that key (default `v1`). This stage
supports one configured key, not an automatic rotation/keyring workflow. Unknown
key versions, wrong keys, malformed envelopes, invalid payloads and authentication
failures fail closed with payload-free errors. Retain old keys and plan explicit
re-encryption before changing the configured key/version on a populated database.

## Repository boundary

Construct `db.birth_profiles.BirthProfileRepository(session, encryption,
policy_version=settings.oria_policy_version)` inside the caller's transaction.
`save(user_id, payload)` creates or replaces the user's profile and returns its
UUID. It locks the active user row and checks current consent before encryption
and persistence, serializing with consent withdrawal and other profile writes.
The same UUID and creation timestamp survive updates; ciphertext and update
timestamp change. It flushes but never commits. No profile is marked active yet.

`get(user_id, profile_id=None)` always scopes reads to an active owner; a supplied
profile UUID is an additional filter. It returns the validated decrypted payload
or `None`. Reading after withdrawal remains possible for future inspect/delete
controls; this is not authorization to calculate a chart or call a model.
Ingress must resolve the trusted internal UUID, never accept it as authentication
from user text. Deleted users cannot read or write through the repository.

Both private Pydantic models redact `repr` and `str`; input details are hidden in
formatted validation errors. Explicit serialization is intentionally available
for encryption and future user-facing profile controls. Never log serialized
payloads, individual fields, validation error dictionaries, or exception locals.
Existing application logging remains the final privacy boundary.

## Verification and continuation

`make verify` covers schema rejection, time modes, nonce freshness, round trips,
wrong keys, tampering, context/version mismatches, ciphertext-only PostgreSQL rows,
owner isolation, consent/deletion guards, concurrent writes, withdrawal ordering,
rollback, repeated migration, downgrade/re-upgrade and metadata drift.
Tests use synthetic profiles and newly generated keys in isolated infrastructure.

Stage 7 connects deterministic collection to this repository; Stage 8 supplies
normalized places. Telegram still pauses after consent and does not collect birth
data. Stage 10 must check consent and explicit confirmation before activation and
invalidate derived results on edits.
