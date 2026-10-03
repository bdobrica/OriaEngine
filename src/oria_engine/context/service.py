"""Caller-owned transaction and user lock fence consent against context operations."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.context.contracts import (
    ContextProvider,
    ContextReply,
    ConversationRequest,
    MemoryKind,
)
from oria_engine.db.conversation_sessions import ConversationSessionRepository
from oria_engine.domain.policy import SAFETY_REPLY, guard_reply, is_high_stakes


class ConversationContext:
    def __init__(self, provider: ContextProvider, policy_version: str) -> None:
        self.provider = provider
        self.policy_version = policy_version

    async def respond(
        self, session: AsyncSession, user_id: UUID, request: ConversationRequest
    ) -> ContextReply:
        scope = await ConversationSessionRepository(session, self.policy_version).get_or_create(
            user_id
        )
        if is_high_stakes(request.filtered_message):
            return ContextReply(response_id="oria-policy", text=SAFETY_REPLY)
        draft = await self.provider.respond(scope, request)
        return ContextReply(response_id=draft.response_id, text=guard_reply(draft.text))

    async def remember(self, session: AsyncSession, user_id: UUID, kind: MemoryKind) -> None:
        scope = await ConversationSessionRepository(session, self.policy_version).get_or_create(
            user_id
        )
        await self.provider.remember(scope, kind)
