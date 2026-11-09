"""Application preparation/acceptance; remote mutation is owned by the post-commit worker."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.context.contracts import ContextReply, ContextUnavailable, ConversationRequest
from oria_engine.context.history import AcceptGenerated, AcceptLocal, PreparedHistoryTurn
from oria_engine.context.projections import LinkedContext
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.db.conversation_sessions import ConversationSessionRepository
from oria_engine.db.history import HistoryRepository, sources_ready
from oria_engine.db.models import ConversationHistoryWork, ConversationSession
from oria_engine.domain.active import ActiveFacts, ActiveIntent, render_active
from oria_engine.domain.policy import guard_reply
from oria_engine.domain.readings import render_linked
from oria_engine.knowledge.contracts import RecordRef
from oria_engine.observability import count
from oria_engine.privacy.encryption import ProfileEncryption
from oria_engine.privacy.messages import prepare_active_input, private_active_input
from oria_engine.queue.limits import UNAVAILABLE_REPLY


class FreezeHistory(Exception):
    """Roll back preparation-side domain work, then durably freeze before generation."""

    def __init__(self, prepared: PreparedHistoryTurn):
        super().__init__("History preparation required")
        self.prepared = prepared


def local_reading(request: ConversationRequest) -> str:
    if request.linked_facts is not None:
        return render_linked(request.linked_facts)
    if request.transit_facts is not None:
        return render_active(
            ActiveFacts(
                intent=ActiveIntent(
                    kind=request.goal,
                    target_timestamp_utc=request.transit_facts.target_timestamp_utc,
                ),
                transits=request.transit_facts,
            )
        ).split("\n", 1)[-1]
    if request.natal_facts is not None and request.goal == "natal_explanation":
        return render_active(
            ActiveFacts(intent=ActiveIntent(kind="natal_explanation"), natal=request.natal_facts)
        ).split("\n", 1)[-1]
    return UNAVAILABLE_REPLY


def approved_text(text: str) -> str:
    original = text
    text = guard_reply(text)
    if text != original:
        count("policy_output_block")
    if len(text.encode("utf-16-le")) // 2 > 4096:
        return "That reading was too long to send. Please ask for a shorter reading."
    return text


@dataclass
class HistoryAttempt:
    session: AsyncSession = field(repr=False)
    user_id: UUID
    event_id: UUID
    encryption: ProfileEncryption = field(repr=False)
    policy: str
    provider: SecondContextProvider = field(repr=False)
    work: ConversationHistoryWork | None = field(default=None, repr=False)
    accepted: AcceptGenerated | AcceptLocal | None = field(default=None, repr=False)
    local_prepared: PreparedHistoryTurn | None = field(default=None, repr=False)
    excluded: bool = False

    async def prepare(self, request: ConversationRequest) -> PreparedHistoryTurn | None:
        if self.excluded or private_active_input(request.filtered_message):
            return None
        linked = LinkedContext(self.session, self.encryption, self.policy, self.provider)
        refs: list[RecordRef] = list(request.knowledge_refs)
        from oria_engine.domain.memory import NO_REMEMBER

        if self.provider.knowledge_enabled and not NO_REMEMBER.search(request.filtered_message):
            refs.extend(await linked.retrieve(self.user_id, request.filtered_message))
        if request.natal_facts is not None or request.transit_facts is not None:
            own = await linked.knowledge.own_birth(self.user_id)
            if own is None:
                return None
            refs.append(own.ref)
        if request.linked_facts is not None:
            refs.extend(request.linked_facts.sources)
        refs = list(dict.fromkeys(refs))
        if refs and not self.provider.knowledge_enabled:
            return None
        if not await sources_ready(
            self.session, self.encryption, self.policy, self.user_id, tuple(refs)
        ):
            return None
        # Source readiness includes the owning service's linked-erasure capability.
        if refs:
            try:
                await self.provider.projection_capabilities(self.user_id)
            except ContextUnavailable:
                return None
        await self.provider.history_capabilities(self.user_id)
        scope = await ConversationSessionRepository(self.session, self.policy).get_or_create(
            self.user_id
        )
        mapping = await self.session.get(ConversationSession, self.user_id)
        assert mapping is not None
        if mapping.history_invalidated:
            unresolved = await self.session.scalar(
                select(
                    exists().where(
                        ConversationHistoryWork.user_id == self.user_id,
                        ConversationHistoryWork.phase != "terminal",
                    )
                )
            )
            if unresolved or any(row.pending for row in await linked.repo.rows(self.user_id)):
                return None
            mapping.session_id, mapping.history_invalidated = uuid4(), False
            scope = scope.model_copy(update={"session_id": mapping.session_id})
        request = request.model_copy(
            update={
                "knowledge_refs": tuple(refs),
                "filtered_message": prepare_active_input(request.filtered_message),
            }
        )
        prepared = self.provider.prepare_history_turn(scope, request, turn_id=self.event_id)
        if mapping.delivery_unconfirmed:
            prepared = prepared.model_copy(
                update={
                    "instructions": prepared.instructions
                    + (
                        "\nApplication delivery state: an earlier accepted reply has unconfirmed "
                        "channel delivery. Do not assume the user read it. Earlier dialogue is "
                        "not current chart facts or proof of a successful save."
                    )
                }
            )
        return prepared

    async def respond(self, request: ConversationRequest) -> ContextReply:
        if self.work is None:
            prepared = await self.prepare(request)
            if prepared is None:
                return ContextReply(
                    response_id="oria-history-local", text=approved_text(local_reading(request))
                )
            raise FreezeHistory(prepared)
        repo = HistoryRepository(self.session, self.encryption, self.policy)
        # Never reconstruct an attempted body from newly calculated facts or clocks.
        prepared = repo.prepared(self.work)
        draft = await self.provider.respond_history(repo.scope(self.work), prepared)
        text = approved_text(draft.text)
        self.accepted = AcceptGenerated(
            contract_version=1,
            user=prepared.user,
            session_id=prepared.session_id,
            turn_id=self.event_id,
            action="accept_generated",
            response_id=draft.response_id,
            assistant_text=text,
        )
        return ContextReply(response_id=draft.response_id, text=text)

    async def local(self, request: ConversationRequest, text: str) -> None:
        """Explicit ordinary conversational/calculated branch only; never a handler catch-all."""
        if (
            self.excluded
            or text != approved_text(text)
            or private_active_input(text)
            or prepare_active_input(text) != text
        ):
            return
        # Local exchanges must already be prepared; do not turn raw birth input into capture.
        if prepare_active_input(request.filtered_message) != request.filtered_message:
            return
        prepared = await self.prepare(request)
        if prepared is None:
            return
        self.local_prepared = prepared
        self.accepted = AcceptLocal(
            contract_version=1,
            user=prepared.user,
            session_id=prepared.session_id,
            turn_id=self.event_id,
            action="accept_local",
            user_text=prepared.input,
            assistant_text=text,
            knowledge_refs=prepared.knowledge_refs,
        )


def history_attempt(session: AsyncSession) -> HistoryAttempt | None:
    value = session.info.get("history_attempt") if isinstance(session.info, dict) else None
    return value if isinstance(value, HistoryAttempt) else None


async def capture_local(session: AsyncSession, request: ConversationRequest, text: str) -> None:
    attempt = history_attempt(session)
    if attempt is not None:
        await attempt.local(request, text)
