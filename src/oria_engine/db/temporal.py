"""Owner/consent-fenced encrypted clarification state. Caller owns transaction."""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.astrology.contracts import WireModel
from oria_engine.db.birth_profiles import ConsentRequiredError
from oria_engine.db.models import TemporalClarification
from oria_engine.db.repositories import ConsentRepository, UserRepository, UserUnavailableError
from oria_engine.domain.temporal import EventAnchor, TemporalMention
from oria_engine.knowledge.contracts import UTCInstant
from oria_engine.privacy.encryption import ProfileEncryption


class PendingTemporal(WireModel):
    schema_version: Literal[1] = 1
    consent_id: UUID
    text: str = Field(min_length=1, max_length=4096)
    reference_time_utc: UTCInstant
    timezone: str | None = None
    timezone_source: Literal["explicit_event", "current_preference"] = "current_preference"
    anchors: tuple[EventAnchor, ...] = Field(default=(), max_length=32)
    unresolved: TemporalMention | None = None
    source_update_id: str = Field(min_length=1, max_length=128)


class TemporalRepository:
    def __init__(self, session: AsyncSession, encryption: ProfileEncryption, policy_version: str):
        self.session, self.encryption, self.policy_version = session, encryption, policy_version

    async def _consent(self, user_id: UUID) -> UUID:
        if await UserRepository(self.session).get(user_id, for_update=True) is None:
            raise UserUnavailableError("User unavailable")
        consent = await ConsentRepository(self.session).current(user_id, self.policy_version)
        if consent is None:
            raise ConsentRequiredError("Current consent required")
        return consent.id

    async def get(self, user_id: UUID) -> PendingTemporal | None:
        consent_id = await self._consent(user_id)
        row = await self.session.get(TemporalClarification, user_id)
        if row is None:
            return None
        now: datetime = (await self.session.execute(select(func.clock_timestamp()))).scalar_one()
        if row.expires_at <= now:
            await self.clear(user_id)
            return None
        draft = PendingTemporal.model_validate_json(
            self.encryption.decrypt_event(
                row.encrypted_payload,
                user_id=user_id,
                event_id=row.id,
                kind="temporal-clarification",
                key_version=row.encryption_key_version,
            )
        )
        if draft.consent_id != consent_id:
            await self.clear(user_id)
            return None
        return draft

    async def save(self, user_id: UUID, draft: PendingTemporal) -> None:
        if await self._consent(user_id) != draft.consent_id:
            raise ConsentRequiredError("Current consent required")
        draft = PendingTemporal.model_validate(draft)
        row = await self.session.get(TemporalClarification, user_id)
        if row is None:
            row = TemporalClarification(user_id=user_id, id=uuid4())
            self.session.add(row)
        row.encrypted_payload = self.encryption.encrypt_event(
            draft.model_dump_json(),
            user_id=user_id,
            event_id=row.id,
            kind="temporal-clarification",
        )
        row.encryption_key_version = self.encryption.key_version
        # Clarification replies do not extend the original message's retention window.
        row.expires_at = draft.reference_time_utc + timedelta(hours=24)
        await self.session.flush()

    async def clear(self, user_id: UUID) -> None:
        await self._consent(user_id)
        await self.session.execute(
            delete(TemporalClarification).where(TemporalClarification.user_id == user_id)
        )
