"""Durable encrypted progress; shares the consent/profile transaction and user lock."""

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.db.birth_profiles import ConsentRequiredError
from oria_engine.db.models import OnboardingProgress, User
from oria_engine.db.repositories import ConsentRepository, UserRepository, UserUnavailableError
from oria_engine.domain.onboarding_data import OnboardingDraft
from oria_engine.privacy.encryption import ProfileEncryption


class OnboardingRepository:
    def __init__(self, session: AsyncSession, encryption: ProfileEncryption, policy_version: str):
        self.session = session
        self.encryption = encryption
        self.policy_version = policy_version

    async def get(self, user_id: UUID) -> OnboardingDraft | None:
        row = await self.session.scalar(
            select(OnboardingProgress)
            .join(User)
            .where(OnboardingProgress.user_id == user_id, User.deleted_at.is_(None))
            .execution_options(populate_existing=True)
        )
        if row is None:
            return None
        return self.encryption.decrypt_draft(
            row.encrypted_payload,
            user_id=user_id,
            key_version=row.encryption_key_version,
            schema_version=row.schema_version,
        )

    async def save(self, user_id: UUID, draft: OnboardingDraft) -> None:
        if await UserRepository(self.session).get(user_id, for_update=True) is None:
            raise UserUnavailableError("User unavailable")
        consent = await ConsentRepository(self.session).current(user_id, self.policy_version)
        if consent is None or consent.id != draft.consent_id:
            raise ConsentRequiredError("Current consent required")
        row = await self.session.get(OnboardingProgress, user_id)
        if row is None:
            row = OnboardingProgress(user_id=user_id)
            self.session.add(row)
        row.encrypted_payload = self.encryption.encrypt_draft(draft, user_id=user_id)
        row.encryption_key_version = self.encryption.key_version
        row.schema_version = draft.schema_version
        row.updated_at = (await self.session.execute(select(func.clock_timestamp()))).scalar_one()
        await self.session.flush()

    async def clear(self, user_id: UUID) -> None:
        if await UserRepository(self.session).get(user_id, for_update=True) is None:
            raise UserUnavailableError("User unavailable")
        await self.session.execute(
            delete(OnboardingProgress).where(OnboardingProgress.user_id == user_id)
        )
