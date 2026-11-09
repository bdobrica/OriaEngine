"""Encrypted desired projections and durable, owner-scoped delivery state.

Canonical references, never retrieved narratives, authorize use. Caller holds the
owner lock/transaction. Erasure work survives withdrawal and remote outages.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.db.knowledge import KnowledgeRepository
from oria_engine.db.models import ContextProjectionWork
from oria_engine.knowledge.contracts import ContextProjection, RecordRef
from oria_engine.privacy.encryption import ProfileEncryption


class ProjectionRepository:
    def __init__(self, session: AsyncSession, encryption: ProfileEncryption, policy_version: str):
        self.session, self.encryption, self.policy_version = session, encryption, policy_version
        self.knowledge = KnowledgeRepository(session, encryption, policy_version)

    async def rows(self, user_id: UUID) -> list[ContextProjectionWork]:
        return list(
            await self.session.scalars(
                select(ContextProjectionWork)
                .where(ContextProjectionWork.user_id == user_id)
                .order_by(ContextProjectionWork.created_at, ContextProjectionWork.id)
            )
        )

    def decode(self, row: ContextProjectionWork) -> ContextProjection:
        assert row.encrypted_payload is not None and row.encryption_key_version is not None
        result = ContextProjection.model_validate_json(
            self.encryption.decrypt_event(
                row.encrypted_payload,
                user_id=row.user_id,
                event_id=row.id,
                kind=f"context-projection-{row.kind}-r{row.revision}",
                key_version=row.encryption_key_version,
            )
        )
        if result.record != self.ref(row):
            raise ValueError("Invalid projection reference")
        return result

    @staticmethod
    def ref(row: ContextProjectionWork) -> RecordRef:
        return RecordRef.model_validate({"kind": row.kind, "id": row.id, "revision": row.revision})

    async def current(self, user_id: UUID, projection: ContextProjection) -> bool:
        for ref in projection.sources:
            saved = await self.knowledge.get(user_id, ref)
            if saved is None or saved.needs_review:
                return False
        return True

    async def put(self, user_id: UUID, projection: ContextProjection) -> None:
        await self.knowledge.lock(user_id, write=True)
        if not await self.current(user_id, projection):
            return
        row = await self.session.get(ContextProjectionWork, (user_id, projection.record.id))
        if row is not None:
            if row.deleted or row.revision > projection.record.revision:
                return
            if row.revision == projection.record.revision:
                # A revision is immutable. Explicit new observations get new UUIDs.
                return
        else:
            if len(await self.rows(user_id)) >= 2000:
                return
            row = ContextProjectionWork(user_id=user_id, id=projection.record.id)
        row.kind, row.revision = projection.record.kind, projection.record.revision
        row.operation_id, row.pending, row.deleted = uuid4(), True, False
        row.attempts, row.next_attempt_at = 0, datetime.now(UTC)
        row.encrypted_payload = self.encryption.encrypt_event(
            projection.model_dump_json(),
            user_id=user_id,
            event_id=row.id,
            kind=f"context-projection-{row.kind}-r{row.revision}",
        )
        row.encryption_key_version = self.encryption.key_version
        self.session.add(row)
        await self.session.flush()

    async def retire(self, row: ContextProjectionWork) -> None:
        if row.deleted:
            return
        row.revision += 1
        row.operation_id, row.pending, row.deleted = uuid4(), True, True
        row.encrypted_payload = row.encryption_key_version = None
        row.attempts, row.next_attempt_at = 0, datetime.now(UTC)

    async def invalidate(self, user_id: UUID, ids: set[UUID], *, erase: bool) -> None:
        from oria_engine.db.history import cancel_history
        from oria_engine.db.models import ConversationSession

        mapping = await self.session.get(ConversationSession, user_id)
        if mapping is not None:
            mapping.history_invalidated = True
        await cancel_history(self.session, user_id, "history_source_changed")
        # Called in the canonical mutation transaction, including when remote use
        # has subsequently been disabled. No deleted sensitive payload stays queued.
        for row in await self.rows(user_id):
            if row.deleted:
                continue
            projection = self.decode(row)
            if row.id in ids and not erase:
                # New canonical revision is staged later; suppress stale use now.
                row.pending = False
                continue
            if row.id in ids or any(ref.id in ids for ref in projection.sources):
                await self.retire(row)
        await self.session.flush()
