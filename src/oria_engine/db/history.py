"""Owner-locked, encrypted transient history work. Repositories never commit."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from oria_engine.context.contracts import ContextScope
from oria_engine.context.history import FINALIZE_REQUEST, FinalizeRequest, PreparedHistoryTurn
from oria_engine.db.models import (
    BirthProfile,
    ConversationHistoryWork,
    ConversationSession,
    InboundEvent,
)
from oria_engine.db.projections import ProjectionRepository
from oria_engine.db.repositories import ConsentRepository
from oria_engine.knowledge.contracts import RecordRef
from oria_engine.privacy.encryption import ProfileEncryption

# The provider may start its 24-hour TTL near the end of a 60-second worker attempt.
# Retain payload-free cancellation IDs through that whole possible interval.
REMOTE_PENDING_LIFETIME = timedelta(hours=24, seconds=60)


async def sources_ready(
    session: AsyncSession,
    encryption: ProfileEncryption,
    policy: str,
    user_id: UUID,
    refs: tuple[RecordRef, ...],
) -> bool:
    repo = ProjectionRepository(session, encryption, policy)
    rows = await repo.rows(user_id)
    # Check stale replacements as well as explicit deletes: either can erase a session.
    for row in rows:
        if row.deleted:
            if row.pending:
                return False
        elif not await repo.current(user_id, repo.decode(row)):
            return False
    ready = {repo.ref(row) for row in rows if not row.deleted and not row.pending}
    return len(refs) <= 20 and {
        RecordRef.model_validate(ref.model_dump()) for ref in refs
    }.issubset(ready)


async def stop_history(session: AsyncSession, event: InboundEvent, code: str) -> None:
    """Wipe text atomically; retain only cancellation IDs until remote pending expiry."""
    work = await session.get(ConversationHistoryWork, event.id)
    if work is not None and work.phase != "terminal":
        if work.receipt is not None or work.accept_attempted:
            mapping = await session.get(ConversationSession, work.user_id)
            if mapping is not None:
                mapping.delivery_unconfirmed = True
        work.encrypted_prepared = work.encrypted_finalize = None
        work.phase = "terminal" if work.receipt is not None else "abandon"
        work.delivery = "cancelled" if work.delivery == "not_attempted" else work.delivery
        work.next_cleanup_at = datetime.now(UTC)
    event.status, event.failure_code = "dead", code
    event.encrypted_input = event.encrypted_reply = None


async def cancel_history(session: AsyncSession, user_id: UUID, code: str) -> None:
    linked = select(ConversationHistoryWork.event_id).where(
        ConversationHistoryWork.user_id == user_id
    )
    owned: ColumnElement[bool] = InboundEvent.id.in_(linked)
    if code in {"consent_changed", "user_unavailable"}:
        # Managed ingress binds consent before any preparation; withdrawal also
        # wipes queued turns that have never reached a provider.
        owned = or_(
            owned,
            InboundEvent.admitted_consent_id.is_not(None) & InboundEvent.is_control.is_(False),
        )
    rows = await session.scalars(
        select(InboundEvent).where(
            InboundEvent.user_id == user_id, InboundEvent.status.not_in(("sent", "dead")), owned
        )
    )
    for event in rows:
        await stop_history(session, event, code)


class HistoryRepository:
    def __init__(self, session: AsyncSession, encryption: ProfileEncryption, policy: str):
        self.session, self.encryption, self.policy = session, encryption, policy

    def encrypt(self, work: ConversationHistoryWork, value: str, kind: str) -> bytes:
        return self.encryption.encrypt_event(
            value, user_id=work.user_id, event_id=work.event_id, kind="history-" + kind
        )

    def decrypt(self, work: ConversationHistoryWork, value: bytes, kind: str) -> str:
        return self.encryption.decrypt_event(
            value,
            user_id=work.user_id,
            event_id=work.event_id,
            kind="history-" + kind,
            key_version=work.encryption_key_version,
        )

    def prepared(self, work: ConversationHistoryWork) -> PreparedHistoryTurn:
        assert work.encrypted_prepared is not None
        return PreparedHistoryTurn.model_validate_json(
            self.decrypt(work, work.encrypted_prepared, "prepared")
        )

    def finalization(self, work: ConversationHistoryWork) -> FinalizeRequest:
        assert work.encrypted_finalize is not None
        return FINALIZE_REQUEST.validate_json(
            self.decrypt(work, work.encrypted_finalize, "finalize")
        )

    async def create(
        self, event: InboundEvent, prepared: PreparedHistoryTurn
    ) -> ConversationHistoryWork:
        assert event.user_id is not None
        consent = await ConsentRepository(self.session).current(event.user_id, self.policy)
        assert consent is not None
        revision = await self.session.scalar(
            select(BirthProfile.revision).where(BirthProfile.user_id == event.user_id)
        )
        now = datetime.now(UTC)
        work = ConversationHistoryWork(
            event_id=event.id,
            user_id=event.user_id,
            session_id=UUID(prepared.session_id),
            consent_id=consent.id,
            policy_version=self.policy,
            profile_revision=revision,
            phase="prepared",
            delivery="not_attempted",
            accept_attempted=False,
            encryption_key_version=self.encryption.key_version,
            cleanup_until=now + REMOTE_PENDING_LIFETIME,
            next_cleanup_at=now,
        )
        work.encrypted_prepared = self.encrypt(work, prepared.model_dump_json(), "prepared")
        self.session.add(work)
        await self.session.flush()
        return work

    def stage(self, work: ConversationHistoryWork, request: FinalizeRequest) -> None:
        work.encrypted_finalize = self.encrypt(work, request.model_dump_json(), "finalize")
        work.encryption_key_version = self.encryption.key_version
        work.phase = "finalize"

    async def valid(self, work: ConversationHistoryWork) -> bool:
        consent = await ConsentRepository(self.session).current(work.user_id, self.policy)
        if consent is None or consent.id != work.consent_id or work.policy_version != self.policy:
            return False
        revision = await self.session.scalar(
            select(BirthProfile.revision).where(BirthProfile.user_id == work.user_id)
        )
        mapping = await self.session.get(ConversationSession, work.user_id)
        if (
            revision != work.profile_revision
            or mapping is None
            or mapping.history_invalidated
            or mapping.session_id != work.session_id
        ):
            return False
        prepared = self.prepared(work)
        if prepared.turn_id != work.event_id or prepared.session_id != str(work.session_id):
            return False
        return await sources_ready(
            self.session, self.encryption, self.policy, work.user_id, tuple(prepared.knowledge_refs)
        )

    @staticmethod
    def scope(work: ConversationHistoryWork) -> ContextScope:
        return ContextScope(user_id=work.user_id, session_id=work.session_id)
