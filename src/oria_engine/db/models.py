"""Canonical identity and consent state; no Telegram profile metadata."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from oria_engine.db.session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SocialIdentity(Base):
    __tablename__ = "social_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_social_identities_provider_user"),
        CheckConstraint("length(trim(provider)) > 0", name="provider_nonempty"),
        CheckConstraint("length(trim(provider_user_id)) > 0", name="provider_user_nonempty"),
        CheckConstraint("length(trim(provider_chat_id)) > 0", name="provider_chat_nonempty"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_user_id: Mapped[str] = mapped_column(String(128))
    provider_chat_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (
        UniqueConstraint("user_id", "revision"),
        CheckConstraint("revision > 0", name="positive_revision"),
        CheckConstraint(
            "policy_version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'", name="policy_version"
        ),
        CheckConstraint("length(trim(channel)) > 0", name="channel_nonempty"),
        CheckConstraint(
            "(status = 'accepted' AND accepted_at IS NOT NULL AND declined_at IS NULL "
            "AND revoked_at IS NULL) OR "
            "(status = 'declined' AND accepted_at IS NULL AND declined_at IS NOT NULL "
            "AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND accepted_at IS NOT NULL AND declined_at IS NULL "
            "AND revoked_at IS NOT NULL AND revoked_at >= accepted_at)",
            name="lifecycle",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    revision: Mapped[int]
    policy_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    channel: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
