"""Caller-owned transaction and user lock fence consent against context operations."""

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.context.contracts import (
    ContextProvider,
    ContextReply,
    ContextUnavailable,
    ConversationRequest,
    MemoryKind,
)
from oria_engine.context.projections import LinkedContext
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.db.conversation_sessions import ConversationSessionRepository
from oria_engine.domain.memory import NO_REMEMBER
from oria_engine.domain.policy import PRIVACY_REPLY, SAFETY_REPLY, guard_reply, is_harmful_request
from oria_engine.domain.readings import interpretation_summary, render_linked
from oria_engine.knowledge.contracts import RecordRef
from oria_engine.observability import count
from oria_engine.privacy.encryption import ProfileEncryption
from oria_engine.privacy.messages import prepare_active_input, private_active_input
from oria_engine.queue.limits import UNAVAILABLE_REPLY


class ConversationContext:
    def __init__(
        self, provider: ContextProvider, policy_version: str, *, enabled: bool = True
    ) -> None:
        self.provider = provider
        self.policy_version = policy_version
        self.enabled = enabled

    async def respond(
        self,
        session: AsyncSession,
        user_id: UUID,
        request: ConversationRequest,
        *,
        encryption: ProfileEncryption | None = None,
        memory_text: str | None = None,
        operation_id: UUID | None = None,
    ) -> ContextReply:
        if not self.enabled:
            return ContextReply(response_id="oria-unavailable", text=UNAVAILABLE_REPLY)
        scope = await ConversationSessionRepository(session, self.policy_version).get_or_create(
            user_id
        )
        if is_harmful_request(request.filtered_message):
            count("policy_high_stakes")
            return ContextReply(response_id="oria-policy", text=SAFETY_REPLY)
        if private_active_input(request.filtered_message):
            count("policy_input_block")
            return ContextReply(response_id="oria-policy", text=PRIVACY_REPLY)
        filtered = prepare_active_input(request.filtered_message)
        if filtered != request.filtered_message:
            request = request.model_copy(
                update={"filtered_message": filtered, "goal": "follow_up", "transit_facts": None}
            )
        if isinstance(session.info, dict) and session.info.get("managed_history_required") is True:
            from oria_engine.context.history_workflow import (
                approved_text,
                history_attempt,
                local_reading,
            )

            attempt = history_attempt(session)
            if attempt is None or attempt.excluded:
                return ContextReply(
                    response_id="oria-history-local", text=approved_text(local_reading(request))
                )
            return await attempt.respond(request)
        linked = None
        calculated = request.linked_facts
        sources = calculated.sources if calculated is not None else ()
        used: tuple[RecordRef, ...] = ()
        if (
            encryption is not None
            and isinstance(self.provider, SecondContextProvider)
            and self.provider.knowledge_enabled
            and not NO_REMEMBER.search(memory_text or request.filtered_message)
        ):
            linked = LinkedContext(session, encryption, self.policy_version, self.provider)
            used = await linked.retrieve(
                user_id,
                memory_text or request.filtered_message,
                sources=sources,
                house_themes=calculated.house_themes if calculated else (),
            )
            if calculated is not None:
                rows = await linked.repo.rows(user_id)
                ready = {
                    linked.repo.ref(row)
                    for row in rows
                    if not row.deleted
                    and not row.pending
                    and await linked.repo.current(user_id, linked.repo.decode(row))
                }
                # New facts must not enter a remote session before its source links
                # can be retained for selective erasure. Post-commit delivery follows.
                if (
                    len(sources) > 20
                    or not set(sources).issubset(ready)
                    or any(r.deleted and r.pending for r in rows)
                ):
                    text = render_linked(calculated)
                    await linked.remember_interpretation(
                        user_id,
                        interpretation_summary(calculated),
                        (),
                        operation_id or uuid4(),
                        canonical_sources=sources,
                        house_themes=calculated.house_themes,
                        calculated_summary=interpretation_summary(calculated),
                    )
                    return ContextReply(response_id="oria-linked-local", text=text)
                used = tuple(dict.fromkeys((*sources, *used)))[:20]
            request = request.model_copy(update={"knowledge_refs": used})
        try:
            draft = await self.provider.respond(scope, request)
        except ContextUnavailable:
            if calculated is None:
                raise
            draft = ContextReply(response_id="oria-linked-local", text=render_linked(calculated))
        text = guard_reply(draft.text)
        if text != draft.text:
            count("policy_output_block")
        if len(text.encode("utf-16-le")) // 2 > 4096:
            text = "That reading was too long to send. Please ask for a shorter reading."
        if linked is not None and text == draft.text:
            await linked.remember_interpretation(
                user_id,
                text,
                used,
                operation_id or uuid4(),
                canonical_sources=sources,
                house_themes=calculated.house_themes if calculated else (),
                calculated_summary=interpretation_summary(calculated) if calculated else None,
            )
        return ContextReply(response_id=draft.response_id, text=text)

    async def remember(self, session: AsyncSession, user_id: UUID, kind: MemoryKind) -> None:
        if not self.enabled:
            return
        scope = await ConversationSessionRepository(session, self.policy_version).get_or_create(
            user_id
        )
        await self.provider.remember(scope, kind)
