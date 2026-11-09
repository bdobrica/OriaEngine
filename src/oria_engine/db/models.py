"""Canonical identity and consent state; no Telegram profile metadata."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    String,
    Text,
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
    # Explicit display/time-resolution preference, never inferred from birthplace.
    current_timezone: Mapped[str | None] = mapped_column(String(128))


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
        CheckConstraint("revision > 0", name="positive_revision"),
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
    revision: Mapped[int] = mapped_column(server_default="1")
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


class TemporalClarification(Base):
    """Short-lived encrypted active-chat progress, not canonical life-event memory."""

    __tablename__ = "temporal_clarifications"
    __table_args__ = (
        CheckConstraint("octet_length(encrypted_payload) >= 29", name="encrypted_envelope"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[UUID] = mapped_column(default=uuid4)
    encrypted_payload: Mapped[bytes]
    encryption_key_version: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class KnowledgeRecord(Base):
    """Canonical payloads are encrypted; deleted UUIDs remain terminal fences."""

    __tablename__ = "knowledge_records"
    __table_args__ = (
        CheckConstraint("kind IN ('entity', 'event')", name="kind"),
        CheckConstraint("revision > 0", name="positive_revision"),
        CheckConstraint(
            "(deleted_at IS NULL AND encrypted_payload IS NOT NULL AND "
            "octet_length(encrypted_payload) >= 29 "
            "AND encryption_key_version IS NOT NULL) OR "
            "(deleted_at IS NOT NULL AND encrypted_payload IS NULL "
            "AND encryption_key_version IS NULL)",
            name="lifecycle",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int]
    encrypted_payload: Mapped[bytes | None]
    encryption_key_version: Mapped[str | None] = mapped_column(String(64))
    needs_review: Mapped[bool] = mapped_column(default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeLink(Base):
    """Dependency edges cannot cross an owner boundary, even through direct SQL."""

    __tablename__ = "knowledge_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "record_id"],
            ["knowledge_records.user_id", "knowledge_records.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "dependency_id"],
            ["knowledge_records.user_id", "knowledge_records.id"],
            ondelete="CASCADE",
            name="fk_knowledge_links_dependency",
        ),
        CheckConstraint("record_id <> dependency_id", name="not_self"),
    )
    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    record_id: Mapped[UUID] = mapped_column(primary_key=True)
    dependency_id: Mapped[UUID] = mapped_column(primary_key=True)


class KnowledgeChange(Base):
    """Provenance without historical copies of corrected/deleted private payloads."""

    __tablename__ = "knowledge_changes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "record_id"],
            ["knowledge_records.user_id", "knowledge_records.id"],
            ondelete="CASCADE",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    record_id: Mapped[UUID] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(primary_key=True)
    source_message_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeOperation(Base):
    """Payload-free inbound mutation receipt, retained across selective erasure."""

    __tablename__ = "knowledge_operations"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    source_message_id: Mapped[UUID] = mapped_column(primary_key=True)


class KnowledgeDialogue(Base):
    """Encrypted bounded focus/selection state, never model-granted mutation authority."""

    __tablename__ = "knowledge_dialogues"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[UUID] = mapped_column(default=uuid4)
    encrypted_payload: Mapped[bytes]
    encryption_key_version: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = (
        CheckConstraint("octet_length(encrypted_payload) >= 29", name="encrypted_envelope"),
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
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
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
    is_control: Mapped[bool] = mapped_column(server_default="false")
    admitted_consent_id: Mapped[UUID | None]


class ConversationSession(Base):
    """One stable external session per internal subject under the MVP policy."""

    __tablename__ = "conversation_sessions"
    __table_args__ = (UniqueConstraint("session_id"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    session_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    history_invalidated: Mapped[bool] = mapped_column(server_default="false")
    delivery_unconfirmed: Mapped[bool] = mapped_column(server_default="false")


class ConversationHistoryWork(Base):
    """One encrypted transient exchange per ingress event; no local transcript archive."""

    __tablename__ = "conversation_history_work"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('prepared','finalize','accepted','abandon','terminal')", name="phase"
        ),
        CheckConstraint(
            "delivery IN ('not_attempted','unknown','failed','sent','cancelled')", name="delivery"
        ),
        CheckConstraint(
            "phase NOT IN ('abandon','terminal') OR "
            "(encrypted_prepared IS NULL AND encrypted_finalize IS NULL)",
            name="terminal_payload",
        ),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_events.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[UUID]
    consent_id: Mapped[UUID]
    policy_version: Mapped[str] = mapped_column(String(64))
    profile_revision: Mapped[int | None]
    phase: Mapped[str] = mapped_column(String(16))
    delivery: Mapped[str] = mapped_column(String(16), default="not_attempted")
    encrypted_prepared: Mapped[bytes | None]
    encrypted_finalize: Mapped[bytes | None]
    encryption_key_version: Mapped[str] = mapped_column(String(64))
    receipt: Mapped[str | None] = mapped_column(Text)
    accept_attempted: Mapped[bool] = mapped_column(default=False)
    cleanup_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_cleanup_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeletionJob(Base):
    """Durable purge progress; survives removal of the user and routing identity."""

    __tablename__ = "deletion_jobs"
    __table_args__ = (
        UniqueConstraint("user_id"),
        CheckConstraint(
            "status IN ('confirmation', 'requested', 'local_deleted', 'context_deleted', "
            "'redis_deleted', 'completed')",
            name="status",
        ),
        CheckConstraint("attempts >= 0", name="attempts"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID]  # Deliberately not a foreign key: minimal deletion marker.
    status: Mapped[str] = mapped_column(String(32), default="confirmation")
    confirmation_token: Mapped[str | None] = mapped_column(String(32))
    confirmation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    encrypted_target: Mapped[bytes | None]
    encryption_key_version: Mapped[str | None] = mapped_column(String(64))
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    failure_code: Mapped[str | None] = mapped_column(String(32))


class ContextProjectionWork(Base):
    """Encrypted desired state, replacing obsolete payloads; no raw values in retry state."""

    __tablename__ = "context_projection_work"
    __table_args__ = (
        CheckConstraint("kind IN ('entity','event','reading')", name="kind"),
        CheckConstraint("revision > 0 AND attempts >= 0", name="positive_revision"),
        CheckConstraint(
            "(deleted AND encrypted_payload IS NULL AND encryption_key_version IS NULL) OR "
            "(NOT deleted AND encrypted_payload IS NOT NULL "
            "AND octet_length(encrypted_payload) >= 29 "
            "AND encryption_key_version IS NOT NULL)",
            name="lifecycle",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int]
    operation_id: Mapped[UUID]
    encrypted_payload: Mapped[bytes | None]
    encryption_key_version: Mapped[str | None] = mapped_column(String(64))
    deleted: Mapped[bool]
    pending: Mapped[bool]
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
