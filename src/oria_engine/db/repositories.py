"""Repositories share the caller's transaction; user UUIDs come from trusted ingress."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.db.models import Consent, SocialIdentity, User


class UserUnavailableError(LookupError):
    """The user is absent or marked deleted; contains no identifying details."""


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self) -> User:
        user = User()
        self.session.add(user)
        await self.session.flush()
        return user

    async def get(self, user_id: UUID, *, for_update: bool = False) -> User | None:
        query = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        if for_update:
            # FOR NO KEY UPDATE still serializes writers, but permits inbound FK inserts.
            query = query.with_for_update(key_share=True)
        return (await self.session.scalars(query)).one_or_none()


class SocialIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: UUID, identity_id: UUID) -> SocialIdentity | None:
        result = await self.session.scalars(
            select(SocialIdentity)
            .join(User)
            .where(
                SocialIdentity.id == identity_id,
                SocialIdentity.user_id == user_id,
                User.deleted_at.is_(None),
            )
        )
        return result.one_or_none()

    async def _lookup(self, provider: str, provider_user_id: str) -> SocialIdentity | None:
        # Only identity resolution may query before an internal UUID is known.
        result = await self.session.scalars(
            select(SocialIdentity).where(
                SocialIdentity.provider == provider,
                SocialIdentity.provider_user_id == provider_user_id,
            )
        )
        return result.one_or_none()

    async def get_or_create_user_for_social_identity(
        self, *, provider: str, provider_user_id: str, provider_chat_id: str, lock_user: bool = True
    ) -> User:
        """Resolve trusted transport IDs atomically, including simultaneous first contact."""
        identity = await self._lookup(provider, provider_user_id)
        if identity is None:
            try:
                # A uniqueness race rolls back both candidate rows, not caller work.
                async with self.session.begin_nested():
                    user = await UserRepository(self.session).create()
                    identity = SocialIdentity(
                        user_id=user.id,
                        provider=provider,
                        provider_user_id=provider_user_id,
                        provider_chat_id=provider_chat_id,
                    )
                    self.session.add(identity)
                    await self.session.flush()
                return user
            except IntegrityError as error:
                diagnostic = getattr(error.orig, "diag", None)
                if (
                    getattr(diagnostic, "constraint_name", None)
                    != "uq_social_identities_provider_user"
                ):
                    raise
                identity = await self._lookup(provider, provider_user_id)
                if identity is None:
                    raise UserUnavailableError("User unavailable") from None
        existing_user = await UserRepository(self.session).get(
            identity.user_id, for_update=lock_user
        )
        if existing_user is None:
            raise UserUnavailableError("User unavailable")
        identity.provider_chat_id = provider_chat_id
        await self.session.flush()
        return existing_user


class ConsentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest(self, user_id: UUID) -> Consent | None:
        result = await self.session.scalars(
            select(Consent)
            .join(User)
            .where(Consent.user_id == user_id, User.deleted_at.is_(None))
            .order_by(Consent.revision.desc())
            .limit(1)
        )
        return result.one_or_none()

    async def get(self, user_id: UUID, consent_id: UUID) -> Consent | None:
        result = await self.session.scalars(
            select(Consent)
            .join(User)
            .where(
                Consent.user_id == user_id,
                Consent.id == consent_id,
                User.deleted_at.is_(None),
            )
        )
        return result.one_or_none()

    async def current(self, user_id: UUID, policy_version: str) -> Consent | None:
        """Only the latest decision can authorize the configured policy version."""
        consent = await self.latest(user_id)
        if consent and consent.status == "accepted" and consent.policy_version == policy_version:
            return consent
        return None

    async def accept(self, user_id: UUID, policy_version: str, channel: str) -> Consent:
        return await self._decide(user_id, policy_version, channel, "accepted")

    async def decline(self, user_id: UUID, policy_version: str, channel: str) -> Consent:
        return await self._decide(user_id, policy_version, channel, "declined")

    async def _lock_user(self, user_id: UUID) -> None:
        if await UserRepository(self.session).get(user_id, for_update=True) is None:
            raise UserUnavailableError("User unavailable")

    async def _decide(
        self, user_id: UUID, policy_version: str, channel: str, status: str
    ) -> Consent:
        await self._lock_user(user_id)
        previous = await self.latest(user_id)
        if previous and previous.policy_version == policy_version and previous.status == status:
            return previous
        now: datetime = (await self.session.execute(select(func.clock_timestamp()))).scalar_one()
        consent = Consent(
            user_id=user_id,
            revision=previous.revision + 1 if previous else 1,
            policy_version=policy_version,
            status=status,
            channel=channel,
            created_at=now,
            accepted_at=now if status == "accepted" else None,
            declined_at=now if status == "declined" else None,
        )
        self.session.add(consent)
        await self.session.flush()
        return consent

    async def revoke(self, user_id: UUID, channel: str) -> Consent | None:
        """Withdraw the latest acceptance, regardless of a subsequent policy rollout."""
        await self._lock_user(user_id)
        previous = await self.latest(user_id)
        if previous is None or previous.status != "accepted":
            return previous
        now: datetime = (await self.session.execute(select(func.clock_timestamp()))).scalar_one()
        consent = Consent(
            user_id=user_id,
            revision=previous.revision + 1,
            policy_version=previous.policy_version,
            status="revoked",
            channel=channel,
            created_at=now,
            accepted_at=previous.accepted_at,
            revoked_at=now,
        )
        self.session.add(consent)
        await self.session.flush()
        return consent
