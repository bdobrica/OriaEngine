"""Encrypted profile persistence. Caller owns transaction and trusted owner resolution."""

from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.db.models import AstrologyProfile, BirthProfile, User
from oria_engine.db.repositories import ConsentRepository, UserRepository, UserUnavailableError
from oria_engine.domain.birth_profile import BirthProfilePayload
from oria_engine.privacy.encryption import ProfileEncryption


class ConsentRequiredError(PermissionError):
    """No current consent permits a profile write."""


class BirthProfileRepository:
    def __init__(
        self, session: AsyncSession, encryption: ProfileEncryption, *, policy_version: str
    ) -> None:
        self.session = session
        self.encryption = encryption
        self.policy_version = policy_version

    async def _row(self, user_id: UUID, profile_id: UUID | None = None) -> BirthProfile | None:
        query = (
            select(BirthProfile)
            .join(User)
            .where(BirthProfile.user_id == user_id, User.deleted_at.is_(None))
        )
        if profile_id is not None:
            query = query.where(BirthProfile.id == profile_id)
        return (
            await self.session.scalars(query.execution_options(populate_existing=True))
        ).one_or_none()

    async def get(
        self, user_id: UUID, profile_id: UUID | None = None
    ) -> BirthProfilePayload | None:
        row = await self._row(user_id, profile_id)
        if row is None:
            return None
        return self.encryption.decrypt(
            row.encrypted_payload,
            user_id=user_id,
            profile_id=row.id,
            schema_version=row.schema_version,
            key_version=row.encryption_key_version,
        )

    async def save(self, user_id: UUID, payload: BirthProfilePayload) -> UUID:
        if await UserRepository(self.session).get(user_id, for_update=True) is None:
            raise UserUnavailableError("User unavailable")
        if await ConsentRepository(self.session).current(user_id, self.policy_version) is None:
            raise ConsentRequiredError("Current consent required")
        row = await self._row(user_id)
        profile_id = row.id if row is not None else uuid4()
        encrypted = self.encryption.encrypt(payload, user_id=user_id, profile_id=profile_id)
        await self.session.execute(
            delete(AstrologyProfile).where(AstrologyProfile.user_id == user_id)
        )
        if row is None:
            row = BirthProfile(id=profile_id, user_id=user_id)
            self.session.add(row)
        row.encrypted_payload = encrypted
        row.encryption_key_version = self.encryption.key_version
        row.schema_version = payload.schema_version
        row.updated_at = (await self.session.execute(select(func.clock_timestamp()))).scalar_one()
        await self.session.flush()
        return profile_id
