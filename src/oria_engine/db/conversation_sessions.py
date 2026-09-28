"""Canonical session mapping; no messages, chart facts or transport identities."""

from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.context.contracts import ContextScope
from oria_engine.db.birth_profiles import ConsentRequiredError
from oria_engine.db.models import ConversationSession
from oria_engine.db.repositories import ConsentRepository, UserRepository, UserUnavailableError


class ConversationSessionRepository:
    def __init__(self, session: AsyncSession, policy_version: str) -> None:
        self.session = session
        self.policy_version = policy_version

    async def get_or_create(self, user_id: UUID) -> ContextScope:
        if await UserRepository(self.session).get(user_id, for_update=True) is None:
            raise UserUnavailableError("User unavailable")
        if await ConsentRepository(self.session).current(user_id, self.policy_version) is None:
            raise ConsentRequiredError("Current consent required")
        row = await self.session.scalar(
            select(ConversationSession).where(ConversationSession.user_id == user_id)
        )
        if row is None:
            # Deterministic across a caller rollback after a downstream session creation.
            # A deleted/re-registered user gets a new internal UUID and therefore a new scope.
            row = ConversationSession(user_id=user_id, session_id=uuid5(user_id, "oria-session-v1"))
            self.session.add(row)
            await self.session.flush()
        return ContextScope(user_id=user_id, session_id=row.session_id)
