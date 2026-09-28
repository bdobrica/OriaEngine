import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from oria_engine.context.contracts import ConversationRequest
from oria_engine.context.service import ConversationContext
from oria_engine.db.birth_profiles import ConsentRequiredError
from oria_engine.db.conversation_sessions import ConversationSessionRepository
from oria_engine.db.models import Consent, ConversationSession, User
from oria_engine.db.repositories import ConsentRepository, UserRepository, UserUnavailableError

from .conftest import migrate


@pytest.fixture
async def subjects(database, infrastructure):
    migrate(infrastructure[0], "upgrade", "head")
    async with database.transaction() as session:
        users = [await UserRepository(session).create() for _ in range(2)]
        ids = [user.id for user in users]
        for identifier in ids:
            await ConsentRepository(session).accept(identifier, "test-context", "test")
    try:
        yield ids
    finally:
        async with database.transaction() as session:
            for model in (ConversationSession, Consent):
                await session.execute(delete(model).where(model.user_id.in_(ids)))
            await session.execute(delete(User).where(User.id.in_(ids)))


async def test_stable_sessions_concurrent_reuse_and_rollback(database, subjects):
    async def get(identifier):
        async with database.transaction() as session:
            return await ConversationSessionRepository(session, "test-context").get_or_create(
                identifier
            )

    first, duplicate = await asyncio.gather(get(subjects[0]), get(subjects[0]))
    other = await get(subjects[1])
    assert first == duplicate
    assert first.session_id != other.session_id
    assert first.user_id == subjects[0]
    async with database.transaction() as session:
        assert len(list(await session.scalars(select(ConversationSession)))) == 2
    async with database.transaction() as session:
        await session.execute(
            delete(ConversationSession).where(ConversationSession.user_id == subjects[0])
        )
    with pytest.raises(RuntimeError):
        async with database.transaction() as session:
            recreated = await ConversationSessionRepository(session, "test-context").get_or_create(
                subjects[0]
            )
            assert recreated == first
            raise RuntimeError()
    assert await get(subjects[0]) == first


async def test_context_requires_current_consent_and_live_owner(database, subjects):
    mock = AsyncMock()
    service = ConversationContext(mock, "test-context")
    request = ConversationRequest(filtered_message="Synthetic topic")
    async with database.transaction() as session:
        await service.respond(session, subjects[0], request)
        await service.remember(session, subjects[0], "concise_readings")
    assert mock.respond.await_args.args[0].user_id == subjects[0]
    async with database.transaction() as session:
        await ConsentRepository(session).revoke(subjects[0], "test")
    for operation in ("respond", "remember"):
        with pytest.raises(ConsentRequiredError):
            async with database.transaction() as session:
                if operation == "respond":
                    await service.respond(session, subjects[0], request)
                else:
                    await service.remember(session, subjects[0], "concise_readings")
    with pytest.raises(ConsentRequiredError):
        async with database.transaction() as session:
            await ConversationContext(mock, "new-policy").respond(session, subjects[1], request)
    async with database.transaction() as session:
        user = await session.get(User, subjects[1])
        user.deleted_at = datetime.now(UTC)
    for identifier in (subjects[1], uuid4()):
        with pytest.raises(UserUnavailableError):
            async with database.transaction() as session:
                await service.respond(session, identifier, request)
    assert mock.respond.await_count == mock.remember.await_count == 1


async def test_user_lock_fences_consent_withdrawal(database, subjects):
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(*args):
        entered.set()
        await release.wait()

    mock = AsyncMock()
    mock.respond.side_effect = respond

    async def conversation():
        async with database.transaction() as session:
            await ConversationContext(mock, "test-context").respond(
                session, subjects[0], ConversationRequest(filtered_message="Hello")
            )

    async def revoke():
        async with database.transaction() as session:
            await ConsentRepository(session).revoke(subjects[0], "test")

    task = asyncio.create_task(conversation())
    await entered.wait()
    withdrawal = asyncio.create_task(revoke())
    try:
        await asyncio.sleep(0.05)
        assert not withdrawal.done()
    finally:
        release.set()
        await asyncio.gather(task, withdrawal)
