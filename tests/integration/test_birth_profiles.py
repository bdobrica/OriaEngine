import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text

from oria_engine.db.birth_profiles import BirthProfileRepository, ConsentRequiredError
from oria_engine.db.models import BirthProfile, Consent, SocialIdentity, User
from oria_engine.db.repositories import ConsentRepository, UserRepository, UserUnavailableError
from oria_engine.privacy.encryption import ProfileEncryptionError

from .conftest import migrate


@pytest.fixture
async def store(database, infrastructure):
    migrate(infrastructure[0], "upgrade", "head")
    try:
        yield database
    finally:
        async with database.transaction() as session:
            for model in (BirthProfile, Consent, SocialIdentity, User):
                await session.execute(delete(model))


def repo(session, encryption, policy="v1"):
    return BirthProfileRepository(session, encryption, policy_version=policy)


async def owner(session):
    user = await UserRepository(session).create()
    await ConsentRepository(session).accept(user.id, "v1", "telegram")
    return user.id


async def test_encrypted_storage_update_and_scoping(store, encryption, birth_payload):
    async with store.transaction() as session:
        user_id = await owner(session)
        other = await owner(session)
        profile_id = await repo(session, encryption).save(user_id, birth_payload)
    async with store.transaction() as session:
        assert await repo(session, encryption).get(user_id, profile_id) == birth_payload
        assert await repo(session, encryption).get(other, profile_id) is None
        assert await repo(session, encryption).get(other) is None
        assert await repo(session, encryption).get(uuid4()) is None
        raw = (
            await session.execute(text("SELECT row_to_json(p)::text FROM birth_profiles p"))
        ).scalar_one()
        for value in ("1990-04-13", "03:42:00", "Cluj", "46.7712", "Europe/Bucharest"):
            assert value not in raw
        row = await session.get(BirthProfile, profile_id)
        original = row.encrypted_payload
        created, updated = row.created_at, row.updated_at
        assert row.schema_version == 1 and row.encryption_key_version == "v1"
    replacement = birth_payload.model_copy(
        update={"birth_local_time": None, "birth_time_accuracy": "unknown"}
    )
    async with store.transaction() as session:
        assert await repo(session, encryption).save(user_id, replacement) == profile_id
        assert await repo(session, encryption).get(user_id) == replacement
        row = await session.get(BirthProfile, profile_id)
        assert row.encrypted_payload != original
        assert row.created_at == created and row.updated_at > updated
        assert await session.scalar(select(func.count()).select_from(BirthProfile)) == 1


async def test_consent_and_deleted_user_guards(store, encryption, birth_payload):
    async with store.transaction() as session:
        user = await UserRepository(session).create()
        repository = repo(session, encryption)
        with pytest.raises(ConsentRequiredError):
            await repository.save(user.id, birth_payload)
        consents = ConsentRepository(session)
        await consents.decline(user.id, "v1", "telegram")
        with pytest.raises(ConsentRequiredError):
            await repository.save(user.id, birth_payload)
        await consents.accept(user.id, "v1", "telegram")
        with pytest.raises(ConsentRequiredError):
            await repo(session, encryption, "v2").save(user.id, birth_payload)
        await repository.save(user.id, birth_payload)
        await consents.revoke(user.id, "telegram")
        with pytest.raises(ConsentRequiredError):
            await repository.save(user.id, birth_payload)
        # Reads remain available for future inspect/delete controls after withdrawal.
        assert await repository.get(user.id) == birth_payload
        user.deleted_at = await session.scalar(select(func.clock_timestamp()))
        await session.flush()
        assert await repository.get(user.id) is None
        for user_id in (user.id, uuid4()):
            with pytest.raises(UserUnavailableError):
                await repository.save(user_id, birth_payload)


async def test_rollback_and_concurrent_writes(store, encryption, birth_payload):
    async with store.transaction() as session:
        user_id = await owner(session)
    with pytest.raises(RuntimeError):
        async with store.transaction() as session:
            await repo(session, encryption).save(user_id, birth_payload)
            raise RuntimeError()
    async with store.transaction() as session:
        assert await repo(session, encryption).get(user_id) is None

    async def save():
        async with store.transaction() as session:
            return await repo(session, encryption).save(user_id, birth_payload)

    ids = await asyncio.wait_for(asyncio.gather(save(), save(), save()), timeout=15)
    assert len(set(ids)) == 1


async def test_swapped_ciphertext_fails_authentication(store, encryption, birth_payload):
    async with store.transaction() as session:
        first, second = await owner(session), await owner(session)
        a = await repo(session, encryption).save(first, birth_payload)
        b = await repo(session, encryption).save(second, birth_payload)
        row_a, row_b = await session.get(BirthProfile, a), await session.get(BirthProfile, b)
        row_b.encrypted_payload = row_a.encrypted_payload
    async with store.transaction() as session:
        with pytest.raises(ProfileEncryptionError):
            await repo(session, encryption).get(second)


async def test_withdrawal_serializes_before_profile_write(store, encryption, birth_payload):
    async with store.transaction() as session:
        user_id = await owner(session)
    started = asyncio.Event()

    async def save():
        async with store.transaction() as session:
            started.set()
            with pytest.raises(ConsentRequiredError):
                await repo(session, encryption).save(user_id, birth_payload)

    async with store.transaction() as session:
        await ConsentRepository(session).revoke(user_id, "telegram")
        task = asyncio.create_task(save())
        await started.wait()
    await asyncio.wait_for(task, timeout=15)
    async with store.transaction() as session:
        assert await repo(session, encryption).get(user_id) is None
