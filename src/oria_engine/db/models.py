"""Canonical identity and consent state; no Telegram profile metadata."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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


class BirthProfile(Base):
    __tablename__ = "birth_profiles"
    __table_args__ = (
        UniqueConstraint("user_id"),
        CheckConstraint("schema_version > 0", name="positive_schema_version"),
        CheckConstraint("octet_length(encrypted_payload) >= 29", name="encrypted_envelope"),
        CheckConstraint(
            "encryption_key_version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'",
            name="encryption_key_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    encrypted_payload: Mapped[bytes]
    encryption_key_version: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OnboardingProgress(Base):
    __tablename__ = "onboarding_drafts"
    __table_args__ = (
        CheckConstraint("schema_version = 1", name="schema_version"),
        CheckConstraint("octet_length(encrypted_payload) >= 29", name="encrypted_envelope"),
        CheckConstraint(
            "encryption_key_version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'",
            name="encryption_key_version",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    encrypted_payload: Mapped[bytes]
    encryption_key_version: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AstrologyProfile(Base):
    """Disposable user-scoped cache; validity is checked against source and versions."""

    __tablename__ = "astrology_profiles"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    source_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("birth_profiles.id", ondelete="CASCADE")
    )
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_schema_version: Mapped[int]
    calculation_versions: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InboundEvent(Base):
    """Canonical idempotency anchor; sensitive transient fields are encrypted."""

    __tablename__ = "inbound_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_update_id"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'sent', 'dead')", name="status"
        ),
        CheckConstraint("attempts >= 0 AND attempts <= 5", name="attempts"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_update_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    encrypted_input: Mapped[bytes | None]
    encrypted_reply: Mapped[bytes | None]
    encryption_key_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    failure_code: Mapped[str | None] = mapped_column(String(32))


class ConversationSession(Base):
    """One stable external session per internal subject under the MVP policy."""

    __tablename__ = "conversation_sessions"
    __table_args__ = (UniqueConstraint("session_id"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    session_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
