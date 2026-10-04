"""Confirmed, durable deletion using the owning services' public boundaries."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.context.contracts import ContextProvider
from oria_engine.db.models import (
    AstrologyProfile,
    BirthProfile,
    Consent,
    ConversationSession,
    DeletionJob,
    InboundEvent,
    OnboardingProgress,
    SocialIdentity,
    User,
)
from oria_engine.db.repositories import UserRepository, UserUnavailableError
from oria_engine.db.session import Database
from oria_engine.domain.channel import ChannelButton, ChannelClient, ChannelMessage
from oria_engine.domain.consent import ConsentReply, OnboardingState
from oria_engine.privacy.encryption import ProfileEncryption

logger = logging.getLogger(__name__)
FINAL_TEXT = (
    "Deletion is complete for your previous Oria account: birth details, chart, consent "
    "history, application sessions and SecondContext conversation/memory data are removed. "
    "Minimal deletion and unlinked update receipts remain to prevent replay. Backups, "
    "AI-provider retention and Telegram messages have separate lifecycles. "
    "Use /start to begin again with a new account and fresh consent."
)


async def admission_lock(session: AsyncSession, provider: str, provider_user_id: str) -> None:
    # Same fence at ingress and final identity removal. No private value leaves PostgreSQL.
    await session.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(f"oria:admission:{provider}:{provider_user_id}", 0)
            )
        )
    )


async def deletion_command(
    session: AsyncSession, user_id: UUID, message: ChannelMessage, command: str | None
) -> ConsentReply | None:
    if command not in {"delete-me", "delete_me"} and not (
        message.callback_data and message.callback_data.startswith("delete:")
    ):
        return None
    user = await UserRepository(session).get(user_id, for_update=True)
    if user is None:
        raise UserUnavailableError("User unavailable")
    job = await session.scalar(
        select(DeletionJob).where(DeletionJob.user_id == user_id).with_for_update()
    )
    now = datetime.now(UTC)
    if command in {"delete-me", "delete_me"}:
        if job is None:
            job = DeletionJob(user_id=user_id, next_attempt_at=now)
            session.add(job)
        job.confirmation_token = uuid4().hex
        job.confirmation_expires_at = now + timedelta(minutes=15)
        await session.flush()
        return ConsentReply(
            OnboardingState.CLOSED,
            "Delete your Oria account and its saved birth details, chart, consent history "
            "and SecondContext conversations/memories? This cannot be undone. Processing "
            "stops after confirmation; cleanup retries if a service is unavailable. "
            "Backups, AI-provider retention and Telegram messages are separate. Minimal "
            "deletion/update receipts remain. Confirm below within 15 minutes, or cancel.",
            (
                ChannelButton("Yes, delete my account", f"delete:confirm:{job.confirmation_token}"),
                ChannelButton("Cancel", f"delete:cancel:{job.confirmation_token}"),
            ),
        )
    if (
        job is None
        or job.status != "confirmation"
        or not job.confirmation_token
        or job.confirmation_expires_at is None
        or job.confirmation_expires_at <= now
        or message.callback_data
        not in {
            f"delete:confirm:{job.confirmation_token}",
            f"delete:cancel:{job.confirmation_token}",
        }
    ):
        return ConsentReply(
            OnboardingState.CLOSED, "This deletion button is stale. Use /delete_me again."
        )
    if message.callback_data == f"delete:cancel:{job.confirmation_token}":
        await session.delete(job)
        return ConsentReply(OnboardingState.CLOSED, "Deletion cancelled. Use /start to resume.")
    job.status = "requested"
    job.requested_at = now
    job.next_attempt_at = now
    job.confirmation_token = None
    job.confirmation_expires_at = None
    user.deleted_at = now  # Same owner lock as all conversation/consent/profile mutations.
    return ConsentReply(
        OnboardingState.CLOSED, "Deletion requested. Conversation processing is stopped."
    )


class DeletionWorker:
    def __init__(
        self,
        database: Database,
        redis: Redis,
        encryption: ProfileEncryption,
        context: ContextProvider,
        client: ChannelClient,
    ) -> None:
        self.database = database
        self.redis = redis
        self.encryption = encryption
        self.context = context
        self.client = client

    async def recover(self) -> None:
        async with self.database.transaction() as session:
            now = datetime.now(UTC)
            await session.execute(
                delete(DeletionJob).where(
                    DeletionJob.status == "confirmation", DeletionJob.confirmation_expires_at <= now
                )
            )
            identifiers = list(
                await session.scalars(
                    select(DeletionJob.id)
                    .where(
                        DeletionJob.status != "confirmation",
                        DeletionJob.next_attempt_at <= now,
                        (DeletionJob.status != "completed")
                        | DeletionJob.encrypted_target.is_not(None),
                    )
                    .order_by(DeletionJob.next_attempt_at)
                    .limit(4)
                )
            )
        # One slow dependency must not strand unrelated subjects.
        await asyncio.gather(*(self.process(i) for i in identifiers))

    async def process(self, identifier: UUID) -> None:
        try:
            async with asyncio.timeout(60):
                while await self.step(identifier):
                    pass
        except Exception:
            async with self.database.transaction() as session:
                job = await session.scalar(
                    select(DeletionJob).where(DeletionJob.id == identifier).with_for_update()
                )
                if job is not None and (
                    job.status != "completed" or job.encrypted_target is not None
                ):
                    job.attempts += 1
                    job.failure_code = "deletion_retry"
                    job.next_attempt_at = datetime.now(UTC) + timedelta(
                        seconds=min(5 * 2 ** min(job.attempts, 10), 3600)
                    )
            logger.warning("deletion_retry")

    async def step(self, identifier: UUID) -> bool:
        async with self.database.transaction() as session:
            job = await session.scalar(
                select(DeletionJob)
                .where(DeletionJob.id == identifier)
                .with_for_update(skip_locked=True)
            )
            now = datetime.now(UTC)
            if job is None or job.status == "confirmation" or job.next_attempt_at > now:
                return False
            if job.status == "requested":
                # Confirmation has fenced the owner. Keep routing only until final cleanup.
                await session.execute(
                    select(User).where(User.id == job.user_id).with_for_update(key_share=True)
                )
                for model in (
                    AstrologyProfile,
                    BirthProfile,
                    OnboardingProgress,
                    ConversationSession,
                    Consent,
                ):
                    await session.execute(delete(model).where(model.user_id == job.user_id))
                await session.execute(
                    update(InboundEvent)
                    .where(InboundEvent.user_id == job.user_id)
                    .values(
                        status="dead", encrypted_input=None, encrypted_reply=None, failure_code=None
                    )
                )
                job.status = "local_deleted"
            elif job.status == "local_deleted":
                await self.context.purge(job.user_id)
                job.status = "context_deleted"
            elif job.status == "context_deleted":
                # Conversation coordination key. Queue envelopes contain only event UUIDs;
                # terminal/detached PostgreSQL receipts make delayed deliveries inert.
                await self.redis.delete(f"oria:user:{job.user_id}:conversation-lock")
                job.status = "redis_deleted"
            elif job.status == "redis_deleted":
                identities = list(
                    await session.scalars(
                        select(SocialIdentity)
                        .where(SocialIdentity.user_id == job.user_id)
                        .order_by(SocialIdentity.provider, SocialIdentity.provider_user_id)
                    )
                )
                for identity in identities:
                    await admission_lock(session, identity.provider, identity.provider_user_id)
                    if identity.provider == "telegram":
                        prefix = f"oria:abuse:telegram:{identity.provider_user_id}"
                        await self.redis.delete(prefix + ":rate", prefix + ":notice")
                await session.execute(select(User).where(User.id == job.user_id).with_for_update())
                target = next(
                    (i.provider_chat_id for i in identities if i.provider == "telegram"), None
                )
                if target is not None:
                    job.encrypted_target = self.encryption.encrypt_event(
                        target, user_id=job.user_id, event_id=job.id, kind="deletion-target"
                    )
                    job.encryption_key_version = self.encryption.key_version
                    job.notification_expires_at = now + timedelta(hours=24)
                # Unlinked receipts preserve Telegram deduplication after account removal.
                await session.execute(
                    update(InboundEvent)
                    .where(InboundEvent.user_id == job.user_id)
                    .values(
                        user_id=None,
                        status="dead",
                        encrypted_input=None,
                        encrypted_reply=None,
                        failure_code=None,
                        attempts=0,
                    )
                )
                await session.execute(
                    delete(SocialIdentity).where(SocialIdentity.user_id == job.user_id)
                )
                await session.execute(delete(User).where(User.id == job.user_id))
                job.completed_at = now
                job.status = "completed"
            else:
                if job.encrypted_target is not None:
                    if (
                        job.notification_expires_at is not None
                        and now < job.notification_expires_at
                    ):
                        assert job.encryption_key_version is not None
                        target = self.encryption.decrypt_event(
                            job.encrypted_target,
                            user_id=job.user_id,
                            event_id=job.id,
                            kind="deletion-target",
                            key_version=job.encryption_key_version,
                        )
                        await self.client.send_text(target, FINAL_TEXT)
                    job.encrypted_target = None
                    job.encryption_key_version = None
                    job.notification_expires_at = None
                job.failure_code = None
                return False
            job.failure_code = None
            return True
