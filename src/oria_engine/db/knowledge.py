"""Encrypted canonical knowledge; caller owns transaction and authenticated owner.

No remote projection/ingest calls. Owner locks serialize all writes with consent and
account deletion. Record UUIDs are terminal after erasure; provenance stores no old
payloads. Candidate wire DTOs are reused locally without enabling a service route.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, TypeAdapter
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.astrology.contracts import WireModel
from oria_engine.db.birth_profiles import ConsentRequiredError
from oria_engine.db.models import (
    AstrologyProfile,
    BirthProfile,
    KnowledgeChange,
    KnowledgeDialogue,
    KnowledgeLink,
    KnowledgeOperation,
    KnowledgeRecord,
    OnboardingProgress,
    TemporalClarification,
)
from oria_engine.db.repositories import ConsentRepository, UserRepository, UserUnavailableError
from oria_engine.knowledge.contracts import (
    CanonicalRecord,
    EntityRecord,
    EventRecord,
    RecordRef,
    UTCInstant,
)
from oria_engine.privacy.encryption import ProfileEncryption, ProfileEncryptionError

RECORD: TypeAdapter[EntityRecord | EventRecord] = TypeAdapter(CanonicalRecord)
MAX_RECORDS = 1000


class KnowledgeConflict(ValueError):
    """A stale, unavailable or invalid reference; never include record content."""


@dataclass(frozen=True, repr=False)
class SavedRecord:
    record: EntityRecord | EventRecord = field(repr=False)
    needs_review: bool = False

    @property
    def ref(self) -> RecordRef:
        return RecordRef(kind=self.record.kind, id=self.record.id, revision=self.record.revision)


class MemoryProgress(WireModel):
    consent_id: UUID | None
    reference_time_utc: UTCInstant
    focus: tuple[RecordRef, ...] = Field(default=(), max_length=32)
    action: Literal["read", "delete", "correct", "learn"] | None = None
    text: str = Field(default="", max_length=4096)
    choices: tuple[RecordRef, ...] = Field(default=(), max_length=20)
    # Delete-cascade acknowledgement is a scoped second turn, not a model decision.
    confirm_cascade: bool = False
    cascade_refs: tuple[RecordRef, ...] = Field(default=(), max_length=1000)
    awaiting_date: bool = False
    source_message_id: UUID | None = None
    timezone: str | None = None
    timezone_source: Literal["explicit_event", "current_preference"] = "current_preference"


class KnowledgeRepository:
    def __init__(self, session: AsyncSession, encryption: ProfileEncryption, policy_version: str):
        self.session, self.encryption, self.policy_version = session, encryption, policy_version

    async def lock(self, user_id: UUID, *, write: bool = False) -> UUID | None:
        if await UserRepository(self.session).get(user_id, for_update=True) is None:
            raise UserUnavailableError("User unavailable")
        consent = await ConsentRepository(self.session).current(user_id, self.policy_version)
        if write and consent is None:
            raise ConsentRequiredError("Current consent required")
        return consent.id if consent else None

    async def _row(self, user_id: UUID, record_id: UUID) -> KnowledgeRecord | None:
        return await self.session.get(KnowledgeRecord, (user_id, record_id), populate_existing=True)

    def _decode(self, row: KnowledgeRecord) -> SavedRecord:
        assert row.encrypted_payload is not None and row.encryption_key_version is not None
        try:
            record = RECORD.validate_json(
                self.encryption.decrypt_event(
                    row.encrypted_payload,
                    user_id=row.user_id,
                    event_id=row.id,
                    kind=f"knowledge-{row.kind}-r{row.revision}",
                    key_version=row.encryption_key_version,
                )
            )
            if record.id != row.id or record.kind != row.kind or record.revision != row.revision:
                raise ValueError()
            return SavedRecord(record, row.needs_review)
        except ValueError:
            raise ProfileEncryptionError("Knowledge record could not be decoded") from None

    async def list(self, user_id: UUID) -> tuple[SavedRecord, ...]:
        await self.lock(user_id)
        rows = await self.session.scalars(
            select(KnowledgeRecord)
            .where(KnowledgeRecord.user_id == user_id, KnowledgeRecord.deleted_at.is_(None))
            .order_by(KnowledgeRecord.id)
            .limit(MAX_RECORDS + 1)
        )
        return tuple(self._decode(row) for row in rows)

    async def get(self, user_id: UUID, ref: RecordRef) -> SavedRecord | None:
        await self.lock(user_id)
        row = await self._row(user_id, ref.id)
        if row is None:
            own = await self.own_birth(user_id)
            return own if own is not None and own.ref == ref else None
        if row.deleted_at or row.kind != ref.kind or row.revision != ref.revision:
            return None
        return self._decode(row)

    async def own_birth(self, user_id: UUID) -> SavedRecord | None:
        await self.lock(user_id)
        row = await self.session.scalar(select(BirthProfile).where(BirthProfile.user_id == user_id))
        if row is None:
            return None
        return SavedRecord(
            EventRecord(
                id=row.id,
                revision=row.revision,
                event_type="birth",
                description="your birth",
                source_message_id=row.id,
                natal_profile_revision=row.revision,
            )
        )

    async def claim(self, user_id: UUID, source: UUID, *, learning: bool = True) -> bool:
        await self.lock(user_id, write=learning)
        if await self.session.get(KnowledgeOperation, (user_id, source)) is not None:
            return False
        self.session.add(KnowledgeOperation(user_id=user_id, source_message_id=source))
        await self.session.flush()
        return True

    async def save(self, user_id: UUID, record: EntityRecord | EventRecord) -> SavedRecord:
        await self.lock(user_id, write=True)
        record = RECORD.validate_python(record)
        row = await self._row(user_id, record.id)
        if row is None:
            if record.revision != 1:
                raise KnowledgeConflict("New records start at revision one")
            count = await self.session.scalar(
                select(func.count())
                .select_from(KnowledgeRecord)
                .where(KnowledgeRecord.user_id == user_id, KnowledgeRecord.deleted_at.is_(None))
            )
            if (count or 0) >= MAX_RECORDS:
                raise KnowledgeConflict("Saved memory limit reached")
            row = KnowledgeRecord(
                user_id=user_id, id=record.id, kind=record.kind, needs_review=False
            )
        elif (
            row.deleted_at is not None
            or row.kind != record.kind
            or record.revision != row.revision + 1
        ):
            raise KnowledgeConflict("Stale or deleted record")
        dependencies: set[UUID] = set()
        if isinstance(record, EventRecord):
            # Own birth remains a virtual reference to the strict natal profile.
            if record.natal_profile_revision is not None:
                raise KnowledgeConflict("Own birth is owned by the natal profile")
            for participant in record.participants:
                other = await self._row(user_id, participant.entity_id)
                if other is None or other.deleted_at or other.kind != "entity":
                    raise KnowledgeConflict("Participant unavailable")
                dependencies.add(other.id)
            anchor = record.temporal.anchor if record.temporal else None
            if anchor:
                if anchor.kind != "event":
                    raise KnowledgeConflict("Anchor must reference an event")
                anchor_record = await self.get(user_id, anchor)
                natal = await self.session.scalar(
                    select(BirthProfile).where(
                        BirthProfile.user_id == user_id,
                        BirthProfile.id == anchor.id,
                        BirthProfile.revision == anchor.revision,
                    )
                )
                if natal is None and (
                    anchor_record is None
                    or anchor_record.needs_review
                    or not isinstance(anchor_record.record, EventRecord)
                ):
                    raise KnowledgeConflict("Anchor unavailable")
                # Reject cycles before persisting an edge.
                if record.id == anchor.id or anchor.id in await self.dependents(user_id, record.id):
                    raise KnowledgeConflict("Cyclic event anchor")
                if natal is None:
                    dependencies.add(anchor.id)
        if row.revision is not None and isinstance(record, EventRecord):
            await self._invalidate(user_id, record.id)
        if row.revision is not None:
            from oria_engine.db.projections import ProjectionRepository

            await ProjectionRepository(
                self.session, self.encryption, self.policy_version
            ).invalidate(user_id, {record.id}, erase=False)
        row.revision = record.revision
        row.encrypted_payload = self.encryption.encrypt_event(
            record.model_dump_json(),
            user_id=user_id,
            event_id=record.id,
            kind=f"knowledge-{record.kind}-r{record.revision}",
        )
        row.encryption_key_version = self.encryption.key_version
        row.needs_review = False
        self.session.add(row)
        await self.session.flush()
        await self.session.execute(
            delete(KnowledgeLink).where(
                KnowledgeLink.user_id == user_id, KnowledgeLink.record_id == record.id
            )
        )
        self.session.add_all(
            KnowledgeLink(user_id=user_id, record_id=record.id, dependency_id=id)
            for id in dependencies
        )
        self.session.add(
            KnowledgeChange(
                user_id=user_id,
                record_id=record.id,
                revision=record.revision,
                source_message_id=record.source_message_id,
            )
        )
        await self.session.flush()
        from oria_engine.db.models import ContextProjectionWork
        from oria_engine.db.projections import ProjectionRepository
        from oria_engine.domain.projections import canonical_projection

        if await self.session.get(ContextProjectionWork, (user_id, record.id)) is not None:
            await ProjectionRepository(self.session, self.encryption, self.policy_version).put(
                user_id, canonical_projection(SavedRecord(record))
            )
        return SavedRecord(record)

    async def dependents(self, user_id: UUID, record_id: UUID) -> set[UUID]:
        await self.lock(user_id)
        edges = (
            await self.session.execute(
                select(KnowledgeLink.record_id, KnowledgeLink.dependency_id).where(
                    KnowledgeLink.user_id == user_id
                )
            )
        ).all()
        found: set[UUID] = set()
        natal = await self.session.scalar(
            select(BirthProfile.id).where(
                BirthProfile.user_id == user_id, BirthProfile.id == record_id
            )
        )
        if natal:
            found.update(
                saved.record.id
                for saved in await self.list(user_id)
                if isinstance(saved.record, EventRecord)
                and saved.record.temporal
                and saved.record.temporal.anchor
                and saved.record.temporal.anchor.id == natal
            )
        frontier = {record_id, *found}
        while frontier:
            following = {a for a, b in edges if b in frontier} - found
            found.update(following)
            frontier = following
        return found

    async def _invalidate(self, user_id: UUID, record_id: UUID) -> None:
        for id in await self.dependents(user_id, record_id):
            row = await self._row(user_id, id)
            if row and row.deleted_at is None:
                row.needs_review = True
        # Any suspended resolution might carry an old anchor/date.
        await self.session.execute(
            delete(TemporalClarification).where(TemporalClarification.user_id == user_id)
        )

    async def invalidate_profile(self, user_id: UUID, profile_id: UUID) -> None:
        """Own-birth events are virtual profile references, never duplicated inputs."""
        await self.lock(user_id, write=True)
        from oria_engine.db.projections import ProjectionRepository

        await ProjectionRepository(self.session, self.encryption, self.policy_version).invalidate(
            user_id, {profile_id}, erase=False
        )
        from oria_engine.db.models import ContextProjectionWork
        from oria_engine.domain.projections import canonical_projection

        if await self.session.get(ContextProjectionWork, (user_id, profile_id)) is not None:
            own = await self.own_birth(user_id)
            if own is not None:
                await ProjectionRepository(self.session, self.encryption, self.policy_version).put(
                    user_id, canonical_projection(own)
                )
        for saved in await self.list(user_id):
            record = saved.record
            if (
                isinstance(record, EventRecord)
                and record.temporal
                and record.temporal.anchor
                and record.temporal.anchor.id == profile_id
            ):
                row = await self._row(user_id, record.id)
                assert row is not None
                row.needs_review = True
                await self._invalidate(user_id, record.id)

    async def erase(self, user_id: UUID, ref: RecordRef) -> int:
        await self.lock(user_id)  # Inspection/erasure do not require current consent.
        saved = await self.get(user_id, ref)
        if saved is None:
            raise KnowledgeConflict("Stale or unavailable record")
        ids = {ref.id, *await self.dependents(user_id, ref.id)}
        from oria_engine.db.projections import ProjectionRepository

        await ProjectionRepository(self.session, self.encryption, self.policy_version).invalidate(
            user_id, ids, erase=True
        )
        now = datetime.now(UTC)
        for id in ids:
            row = await self._row(user_id, id)
            if (
                row is None
                and isinstance(saved.record, EventRecord)
                and saved.record.natal_profile_revision is not None
                and id == ref.id
            ):
                continue
            assert row is not None
            row.revision += 1
            row.deleted_at = now
            row.encrypted_payload = row.encryption_key_version = None
            row.needs_review = False
        await self.session.execute(
            delete(KnowledgeChange).where(
                KnowledgeChange.user_id == user_id, KnowledgeChange.record_id.in_(ids)
            )
        )
        await self.session.execute(
            delete(KnowledgeLink).where(
                KnowledgeLink.user_id == user_id,
                (KnowledgeLink.record_id.in_(ids) | KnowledgeLink.dependency_id.in_(ids)),
            )
        )
        # Pending answers must never restore forgotten content.
        await self.session.execute(
            delete(KnowledgeDialogue).where(KnowledgeDialogue.user_id == user_id)
        )
        await self.session.execute(
            delete(TemporalClarification).where(TemporalClarification.user_id == user_id)
        )
        if (
            isinstance(saved.record, EventRecord)
            and saved.record.natal_profile_revision is not None
        ):
            # Erasing own birth also removes unfinished copies and the derived cache.
            for model in (AstrologyProfile, BirthProfile, OnboardingProgress):
                await self.session.execute(delete(model).where(model.user_id == user_id))
        await self.session.flush()
        return len(ids)

    async def progress(self, user_id: UUID) -> MemoryProgress | None:
        consent = await self.lock(user_id)
        row = await self.session.get(KnowledgeDialogue, user_id)
        if row is None:
            return None
        now = datetime.now(UTC)
        if row.expires_at <= now:
            await self.clear_progress(user_id)
            return None
        progress = MemoryProgress.model_validate_json(
            self.encryption.decrypt_event(
                row.encrypted_payload,
                user_id=user_id,
                event_id=row.id,
                kind="knowledge-dialogue",
                key_version=row.encryption_key_version,
            )
        )
        if progress.consent_id != consent:
            await self.clear_progress(user_id)
            return None
        return progress

    async def set_progress(self, user_id: UUID, progress: MemoryProgress) -> None:
        if progress.consent_id != await self.lock(user_id):
            raise ConsentRequiredError("Consent changed")
        progress = MemoryProgress.model_validate(progress)
        row = await self.session.get(KnowledgeDialogue, user_id)
        if row is None:
            row = KnowledgeDialogue(user_id=user_id, id=uuid4())
            self.session.add(row)
        row.encrypted_payload = self.encryption.encrypt_event(
            progress.model_dump_json(), user_id=user_id, event_id=row.id, kind="knowledge-dialogue"
        )
        row.encryption_key_version = self.encryption.key_version
        row.expires_at = progress.reference_time_utc + timedelta(hours=24)
        await self.session.flush()

    async def clear_progress(self, user_id: UUID) -> None:
        await self.lock(user_id)
        await self.session.execute(
            delete(KnowledgeDialogue).where(KnowledgeDialogue.user_id == user_id)
        )
