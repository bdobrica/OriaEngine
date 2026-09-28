# Identity and consent persistence

`oria_engine.db.models` and `oria_engine.db.repositories` implement the storage
foundation from PLAN sections 12–13. Apply migration `0002` with `make migrate`.
The [Telegram consent flow](consent-flow.md) uses these repositories in Stage 5.

| Table | Stored state |
| --- | --- |
| `users` | Internal UUID, creation timestamp, optional deletion timestamp |
| `social_identities` | UUID, owner UUID, provider, provider user/chat IDs, creation timestamp |
| `consents` | UUID, owner UUID, per-user revision, policy version, status, channel, creation and lifecycle timestamps |

No usernames, display names, phone numbers, photos, arbitrary metadata, or message
payloads are accepted by these repositories. Provider IDs are opaque strings;
the Telegram adapter supplies canonical decimal IDs from authenticated private-chat
updates. Provider user IDs identify a sender; chat IDs route replies. Neither is
an internal user UUID. No Telegram classes enter the persistence layer.

## Repository boundaries

Use one `Database.transaction()` per operation and pass its session to repositories.
Repositories flush but never commit. Identity resolution is the one lookup allowed
before an internal UUID exists: the adapter calls
`SocialIdentityRepository.get_or_create_user_for_social_identity()` with trusted
provider identifiers, then passes the returned UUID to all user-owned operations.
Do not accept a caller-supplied owner UUID as authentication. Repository predicates
provide scoping, not independent authentication or database row-level security.

The unique `(provider, provider_user_id)` constraint arbitrates simultaneous first
contacts. A savepoint rolls back the losing candidate user and identity together,
then resolves the winning row. There is no orphan user or remapping to a different
owner. A repeat contact updates only the reply chat ID. This uses PostgreSQL's
default READ COMMITTED isolation. Stronger isolation requires caller-level retry
of serialization failures. The savepoint pattern follows the
[SQLAlchemy transaction documentation](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#using-savepoint).

`UserRepository.get`, `SocialIdentityRepository.get`, and all consent reads require
an owner UUID. Missing/deleted users cannot gain consent or be reactivated through
identity resolution. `UserUnavailableError` carries no identifying payload.
The deletion workflow and retention policy remain a later stage; foreign keys
restrict hard deletion until owned rows are explicitly removed in that workflow.

## Consent lifecycle

Pass `settings.oria_policy_version` (`ORIA_POLICY_VERSION`) to `accept`, `decline`,
and `current`. The setting already validates a nonempty, maximum 64-character
version identifier. Database constraints enforce that format and valid lifecycle
timestamp combinations. Each decision records its channel without storing UI text.

Consent changes append history; earlier rows remain unchanged. Each write locks
the active user row until the caller commits, then allocates the next per-user
revision. Revisions order decisions independently of clock precision. Consecutive
identical accept/decline decisions for the same policy are idempotent. The [worker queue](worker-queue.md) anchors durable inbound-event deduplication,
including delayed replay handling.

- Accept records `accepted_at`.
- Decline records `declined_at` and immediately makes current consent absent.
- Revoke records `revoked_at` and preserves the withdrawn acceptance timestamp
  and policy version. Repeated revocation is a no-op; with no acceptance it returns
  the existing decision or `None`.
- `current(user_id, policy_version)` returns only the **latest overall decision**
  when it is accepted and matches that version. A newer decline or revocation
  never reveals an older acceptance. A new policy requires a fresh acceptance.

These methods are deterministic persistence operations, not permission for a model
to grant consent. The consent flow calls them only after the corresponding explicit user
action. [Birth-profile writes](birth-profiles.md) take the same user lock and check
current consent to serialize with withdrawal. Future activation must also check
current consent within its own transaction.

## Verification

`make verify` runs real PostgreSQL tests for migration upgrade/repeat/downgrade and
metadata drift, identity uniqueness under concurrent first contacts, routing,
foreign keys, consent lifecycle constraints, concurrent decisions, policy changes,
user scoping, deleted users, and caller rollback. Separate application subprocesses
write and read consent to verify persistence across process restarts.
