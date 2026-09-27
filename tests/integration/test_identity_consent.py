import asyncio
import os
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from oria_engine.config import Settings
from oria_engine.db.models import Consent, SocialIdentity, User
from oria_engine.db.repositories import (
    ConsentRepository,
    SocialIdentityRepository,
    UserRepository,
    UserUnavailableError,
)

from .conftest import migrate


@pytest.fixture
async def store(database, infrastructure):
    migrate(infrastructure[0], "upgrade", "head")
    try:
        yield database
    finally:
        async with database.transaction() as session:
            for model in (Consent, SocialIdentity, User):
                await session.execute(delete(model))


async def resolve(session, provider="telegram", provider_user_id="1001", chat="1001"):
    return await SocialIdentityRepository(session).get_or_create_user_for_social_identity(
        provider=provider, provider_user_id=provider_user_id, provider_chat_id=chat
    )


async def test_user_creation_identity_lookup_and_minimal_routing(store):
    async with store.transaction() as session:
        user = await resolve(session)
        assert user.id.version == 4
        assert user.created_at.tzinfo is not None
        assert (await UserRepository(session).get(user.id)).id == user.id
        assert (await resolve(session, chat="2002")).id == user.id
        # Provider IDs live in separate namespaces.
        assert (await resolve(session, provider="test-channel")).id != user.id
        identity = await session.scalar(
            select(SocialIdentity).where(SocialIdentity.user_id == user.id)
        )
        assert identity.provider_chat_id == "2002"
        assert (await SocialIdentityRepository(session).get(user.id, identity.id)).id == identity.id
        columns = set(SocialIdentity.__table__.columns.keys())
        assert columns == {
            "id",
            "user_id",
            "provider",
            "provider_user_id",
            "provider_chat_id",
            "created_at",
        }


async def test_simultaneous_first_contacts_create_one_user(store):
    barrier = asyncio.Barrier(6)

    async def contact():
        async with store.transaction() as session:
            await barrier.wait()
            return (await resolve(session)).id

    users = await asyncio.wait_for(asyncio.gather(*(contact() for _ in range(6))), timeout=15)
    assert len(set(users)) == 1
    async with store.transaction() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 1
        assert await session.scalar(select(func.count()).select_from(SocialIdentity)) == 1


async def test_database_rejects_duplicate_identity_and_missing_owner(store):
    async with store.transaction() as session:
        user = await resolve(session)
        user_id = user.id
    for owner, provider_id in ((user_id, "1001"), (uuid4(), "9999")):
        with pytest.raises(IntegrityError):
            async with store.transaction() as session:
                session.add(
                    SocialIdentity(
                        user_id=owner,
                        provider="telegram",
                        provider_user_id=provider_id,
                        provider_chat_id=provider_id,
                    )
                )
                await session.flush()


async def test_consent_lifecycle_and_policy_change(store):
    policy = Settings().oria_policy_version
    async with store.transaction() as session:
        user = await resolve(session)
        repo = ConsentRepository(session)
        assert await repo.current(user.id, policy) is None
        assert await repo.revoke(user.id, "telegram") is None
        declined = await repo.decline(user.id, policy, "telegram")
        assert declined.declined_at and declined.accepted_at is None
        assert await repo.current(user.id, policy) is None
        accepted = await repo.accept(user.id, policy, "telegram")
        assert accepted.accepted_at.tzinfo is not None
        assert (await repo.accept(user.id, policy, "telegram")).id == accepted.id
        assert (await repo.current(user.id, policy)).id == accepted.id
        assert await repo.current(user.id, "next-version") is None
        revoked = await repo.revoke(user.id, "telegram")
        assert revoked.revoked_at >= accepted.accepted_at
        assert revoked.accepted_at == accepted.accepted_at
        assert (await repo.revoke(user.id, "telegram")).id == revoked.id
        assert await repo.current(user.id, policy) is None
        assert (await repo.get(user.id, accepted.id)).status == "accepted"
        await repo.accept(user.id, policy, "telegram")
        await repo.decline(user.id, "next-version", "telegram")
        assert await repo.current(user.id, policy) is None
        assert await repo.current(user.id, "next-version") is None
        latest = await repo.accept(user.id, "next-version", "telegram")
        assert (await repo.current(user.id, "next-version")).id == latest.id
        assert await repo.current(user.id, policy) is None
        history = list(
            await session.scalars(
                select(Consent).where(Consent.user_id == user.id).order_by(Consent.revision)
            )
        )
        assert [row.status for row in history] == [
            "declined",
            "accepted",
            "revoked",
            "accepted",
            "declined",
            "accepted",
        ]
        assert [row.revision for row in history] == list(range(1, 7))


async def test_cross_user_scoping_and_deleted_users(store):
    async with store.transaction() as session:
        alice = await resolve(session)
        bob = await resolve(session, provider_user_id="1002", chat="1002")
        identities = SocialIdentityRepository(session)
        consents = ConsentRepository(session)
        alice_identity = await session.scalar(
            select(SocialIdentity).where(SocialIdentity.user_id == alice.id)
        )
        accepted = await consents.accept(alice.id, "v1", "telegram")
        assert await identities.get(bob.id, alice_identity.id) is None
        assert await consents.get(bob.id, accepted.id) is None
        assert await consents.current(bob.id, "v1") is None
        await consents.decline(bob.id, "v1", "telegram")
        await consents.revoke(bob.id, "telegram")
        assert (await consents.current(alice.id, "v1")).id == accepted.id
        alice.deleted_at = await session.scalar(select(func.clock_timestamp()))
        await session.flush()
        assert await UserRepository(session).get(alice.id) is None
        assert await identities.get(alice.id, alice_identity.id) is None
        assert await consents.current(alice.id, "v1") is None
        with pytest.raises(UserUnavailableError):
            await resolve(session)
        with pytest.raises(UserUnavailableError):
            await consents.accept(alice.id, "v1", "telegram")
        with pytest.raises(UserUnavailableError):
            await consents.accept(uuid4(), "v1", "telegram")


async def test_concurrent_consent_decisions_serialize(store):
    async with store.transaction() as session:
        user_id = (await resolve(session)).id

    async def accept():
        async with store.transaction() as session:
            return (await ConsentRepository(session).accept(user_id, "v1", "telegram")).id

    ids = await asyncio.wait_for(asyncio.gather(*(accept() for _ in range(6))), timeout=15)
    assert len(set(ids)) == 1

    async def decide(status):
        async with store.transaction() as session:
            repo = ConsentRepository(session)
            return await getattr(repo, status)(user_id, "v1", "telegram")

    await asyncio.wait_for(asyncio.gather(decide("accept"), decide("decline")), timeout=15)
    async with store.transaction() as session:
        repo = ConsentRepository(session)
        latest = await repo.latest(user_id)
        current = await repo.current(user_id, "v1")
        assert (current is not None) == (latest.status == "accepted")


@pytest.mark.parametrize(
    "values",
    [
        {"status": "unknown"},
        {"status": "accepted"},
        {"status": "declined", "accepted_at": "2026-01-01T00:00:00Z"},
        {"status": "revoked", "revoked_at": "2026-01-01T00:00:00Z"},
        {"status": "declined", "declined_at": "2026-01-01T00:00:00Z", "policy_version": ""},
    ],
)
async def test_database_rejects_invalid_consent(store, values):
    async with store.transaction() as session:
        user_id = (await resolve(session)).id
    with pytest.raises(IntegrityError):
        async with store.transaction() as session:
            # Explicit SQL also proves the constraints do not depend on repository validation.
            params = dict(
                id=uuid4(),
                user_id=user_id,
                policy_version="v1",
                status="declined",
                accepted_at=None,
                declined_at=None,
                revoked_at=None,
            )
            params.update(values)
            await session.execute(
                text(
                    "INSERT INTO consents (id,user_id,revision,policy_version,status,channel,"
                    "accepted_at,declined_at,revoked_at) VALUES "
                    "(:id,:user_id,1,:policy_version,:status,'telegram',"
                    ":accepted_at,:declined_at,:revoked_at)"
                ),
                params,
            )


async def test_caller_rollback_removes_identity_and_consent(store):
    with pytest.raises(RuntimeError):
        async with store.transaction() as session:
            user = await resolve(session)
            await ConsentRepository(session).accept(user.id, "v1", "telegram")
            raise RuntimeError()
    async with store.transaction() as session:
        for model in (User, SocialIdentity, Consent):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_consent_persists_across_application_processes(store, infrastructure):
    env = os.environ.copy()
    env.update(APP_ENV="test", DATABASE_URL=infrastructure[0])
    script = """
import asyncio
from oria_engine.config import Settings
from oria_engine.db.session import Database
from oria_engine.db.repositories import SocialIdentityRepository, ConsentRepository
async def main():
    settings = Settings()
    db = Database(settings)
    try:
        async with db.transaction() as session:
            user = await SocialIdentityRepository(session).get_or_create_user_for_social_identity(
                provider="telegram", provider_user_id="1001", provider_chat_id="1001")
            repo = ConsentRepository(session)
            ACTION
    finally:
        await db.close()
asyncio.run(main())
"""
    for action in (
        'await repo.accept(user.id, settings.oria_policy_version, "telegram")',
        "assert await repo.current(user.id, settings.oria_policy_version) is not None",
    ):
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", script.replace("ACTION", action)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, "Application persistence check failed"
