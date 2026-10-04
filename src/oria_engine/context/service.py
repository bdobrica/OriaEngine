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
from oria_engine.queue.limits import UNAVAILABLE_REPLY


class ConversationContext:
    def __init__(
        self, provider: ContextProvider, policy_version: str, *, enabled: bool = True
    ) -> None:
        self.provider = provider
        self.policy_version = policy_version
        self.enabled = enabled

    async def respond(
        self, session: AsyncSession, user_id: UUID, request: ConversationRequest
    ) -> ContextReply:
        if not self.enabled:
            return ContextReply(response_id="oria-unavailable", text=UNAVAILABLE_REPLY)
        scope = await ConversationSessionRepository(session, self.policy_version).get_or_create(
            user_id
        )
        if is_high_stakes(request.filtered_message):
            return ContextReply(response_id="oria-policy", text=SAFETY_REPLY)
        draft = await self.provider.respond(scope, request)
        text = guard_reply(draft.text)
        if len(text.encode("utf-16-le")) // 2 > 4096:
            text = "That reading was too long to send. Please ask for a shorter reading."
        return ContextReply(response_id=draft.response_id, text=text)

    async def remember(self, session: AsyncSession, user_id: UUID, kind: MemoryKind) -> None:
        if not self.enabled:
            return
        scope = await ConversationSessionRepository(session, self.policy_version).get_or_create(
            user_id
        )
        await self.provider.remember(scope, kind)
