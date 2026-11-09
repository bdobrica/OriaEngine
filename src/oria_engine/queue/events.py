"""PostgreSQL owns queue recovery, ordering, idempotency and bounded payload retention."""

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from redis.exceptions import LockNotOwnedError, RedisError
from sqlalchemy import delete, exists, func, or_, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from oria_engine.astrology.client import AstrologyUnavailable
from oria_engine.context.contracts import ContextUnavailable
from oria_engine.context.history import HistoryFailure, validate_history_receipt
from oria_engine.context.history_workflow import FreezeHistory, HistoryAttempt
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.db.conversation_sessions import ConversationSessionRepository
from oria_engine.db.history import REMOTE_PENDING_LIFETIME, HistoryRepository, stop_history
from oria_engine.db.knowledge import MemoryProgress
from oria_engine.db.models import (
    ConversationHistoryWork,
    ConversationSession,
    InboundEvent,
    KnowledgeDialogue,
    SocialIdentity,
    TemporalClarification,
    User,
)
from oria_engine.db.repositories import ConsentRepository, SocialIdentityRepository
from oria_engine.db.session import Database
from oria_engine.domain.channel import ChannelButton, ChannelClient, ChannelMessage
from oria_engine.domain.consent import ConsentFlow
from oria_engine.domain.memory import privacy_control
from oria_engine.observability import correlation_scope, count, measurement, observed
from oria_engine.privacy.deletion import admission_lock
from oria_engine.privacy.encryption import ProfileEncryption
from oria_engine.queue.limits import (
    LIMIT_REPLY,
    SIZE_REPLY,
    UNAVAILABLE_REPLY,
    AdmissionRejected,
    InboundLimits,
)

logger = logging.getLogger(__name__)
TERMINAL = ("sent", "dead")
MAX_ATTEMPTS = 5
LOCK_SECONDS = 120
PROCESS_SECONDS = 60
RECOVERY_SECONDS = 150


class InputPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    message: ChannelMessage
    command: str | None = None


class ReplyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    text: str = Field(repr=False)
    buttons: tuple[ChannelButton, ...] = Field(default=(), repr=False)
    chat_id: str = Field(repr=False)
    policy_version: str
    consent_id: UUID | None


def terminal(event: InboundEvent, status: str, code: str | None = None) -> None:
    event.status = status
    event.failure_code = code
    event.encrypted_input = None
    event.encrypted_reply = None


def dispatch_head() -> ColumnElement[bool]:
    head = (
        select(InboundEvent.id)
        .where(InboundEvent.user_id == User.id, InboundEvent.status.not_in(TERMINAL))
        .order_by(InboundEvent.sequence)
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )
    control = (
        select(InboundEvent.id)
        .where(
            InboundEvent.user_id == User.id,
            InboundEvent.status.not_in(TERMINAL),
            InboundEvent.is_control.is_(True),
        )
        .order_by(InboundEvent.sequence)
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )
    return or_(InboundEvent.id == head, InboundEvent.id == control)


class EventIngress:
    def __init__(
        self,
        database: Database,
        encryption: ProfileEncryption,
        policy_version: str,
        *,
        limits: InboundLimits | None = None,
        history_enabled: bool = False,
    ):
        self.database = database
        self.encryption = encryption
        self.policy_version = policy_version
        self.limits = limits
        self.history_enabled = history_enabled

    async def publishable(self, identifier: UUID) -> bool:
        async with self.database.transaction() as session:
            return bool(
                await session.scalar(
                    select(
                        exists().where(
                            InboundEvent.id == identifier,
                            InboundEvent.user_id == User.id,
                            InboundEvent.status.not_in(TERMINAL),
                            InboundEvent.next_attempt_at <= datetime.now(UTC),
                            dispatch_head(),
                        )
                    )
                )
            )

    @observed("queue_admission")
    async def accept(self, message: ChannelMessage, *, command: str | None = None) -> UUID:
        async with self.database.transaction() as session:
            await admission_lock(session, message.provider, message.provider_user_id)
            existing_id = await session.scalar(
                select(InboundEvent.id).where(
                    InboundEvent.provider == message.provider,
                    InboundEvent.provider_update_id == message.provider_update_id,
                )
            )
            if existing_id is not None:
                count("update_deduplicated")
                return existing_id
            try:
                oversized = len(message.text.encode("utf-16-le")) // 2 > 4096
            except UnicodeError:
                oversized = True
            if oversized:
                if self.limits is not None:
                    await self.limits.reject(message.provider, message.provider_user_id, SIZE_REPLY)
                raise AdmissionRejected()
            if self.limits is not None and not await self.limits.admit(
                message.provider, message.provider_user_id
            ):
                await self.limits.reject(message.provider, message.provider_user_id, LIMIT_REPLY)
            # Resolve trusted sender identity; the provider/update unique key arbitrates retries.
            user = await SocialIdentityRepository(session).get_or_create_user_for_social_identity(
                provider=message.provider,
                provider_user_id=message.provider_user_id,
                provider_chat_id=message.provider_chat_id,
                lock_user=False,
            )
            # Serialize only admission transactions, independently of slow conversation work.
            # This ensures an earlier sequence commits before a later one becomes visible.
            await session.execute(
                select(
                    func.pg_advisory_xact_lock(func.hashtextextended(f"oria:ingress:{user.id}", 0))
                )
            )
            existing = await session.scalar(
                select(InboundEvent).where(
                    InboundEvent.provider == message.provider,
                    InboundEvent.provider_update_id == message.provider_update_id,
                )
            )
            if existing is not None:
                count("update_deduplicated")
                return existing.id
            control_command = command in {
                "privacy",
                "profile",
                "memories",
                "memory",
                "delete_me",
                "delete-me",
                "help",
            }
            control_callback = bool(
                message.callback_data and message.callback_data.startswith(("consent:", "delete:"))
            )
            control_text = privacy_control(message.text)
            consent = await ConsentRepository(session).current(user.id, self.policy_version)
            # Explicit inspection/erasure controls remain usable after withdrawal.
            # Only bounded selection answers to an existing owner-scoped control
            # are retained; arbitrary pre-consent chat is still discarded.
            import re

            control_answer = bool(
                re.fullmatch(
                    r"(?:[1-9]|1[0-9]|20|yes|cancel|never mind|"
                    r"(?:the )?(?:first|second|third)(?: one)?)",
                    message.text.strip(),
                    re.I,
                )
            )
            if control_answer:
                progress_row = await session.get(KnowledgeDialogue, user.id)
                control_answer = False
                if progress_row is not None and progress_row.expires_at > datetime.now(UTC):
                    # Admission hint only, without waiting on slow owner work. The
                    # domain handler revalidates selection/consent under its lock.
                    progress = MemoryProgress.model_validate_json(
                        self.encryption.decrypt_event(
                            progress_row.encrypted_payload,
                            user_id=user.id,
                            event_id=progress_row.id,
                            kind="knowledge-dialogue",
                            key_version=progress_row.encryption_key_version,
                        )
                    )
                    control_answer = progress.action in {
                        "read",
                        "delete",
                    } and progress.consent_id == (consent.id if consent else None)
            if self.limits is not None and not (
                control_command or control_callback or control_text or control_answer
            ):
                backlog = await session.scalar(
                    select(func.count())
                    .select_from(InboundEvent)
                    .where(
                        InboundEvent.user_id == user.id,
                        InboundEvent.status.not_in(TERMINAL),
                    )
                )
                if backlog is not None and backlog >= self.limits.backlog:
                    await self.limits.reject(
                        message.provider, message.provider_user_id, LIMIT_REPLY
                    )
            # Never durably collect unsolicited birth text before affirmative current consent.
            # The transport normalizes commands. Discard arbitrary callbacks.
            callback = message.callback_data
            buttons = ConsentFlow(self.database, self.policy_version).buttons
            if (
                callback not in {button.data for button in buttons}
                and not (
                    consent and callback and callback.startswith("onboard:") and len(callback) <= 64
                )
                and not (callback and callback.startswith("delete:") and len(callback) <= 64)
            ):
                callback = "stale" if callback is not None else None
            retain = consent or privacy_control(message.text) or control_answer
            message = replace(message, text=message.text if retain else "", callback_data=callback)
            identifier = uuid4()
            now = datetime.now(UTC)
            payload = InputPayload(message=message, command=command)
            statement = (
                insert(InboundEvent)
                .values(
                    id=identifier,
                    user_id=user.id,
                    provider=message.provider,
                    provider_update_id=message.provider_update_id,
                    encrypted_input=self.encryption.encrypt_event(
                        payload.model_dump_json(),
                        user_id=user.id,
                        event_id=identifier,
                        kind="input",
                    ),
                    encryption_key_version=self.encryption.key_version,
                    is_control=bool(
                        control_command or control_callback or control_text or control_answer
                    ),
                    admitted_consent_id=consent.id if consent and self.history_enabled else None,
                    expires_at=now + timedelta(hours=24),
                    next_attempt_at=now,
                )
                .on_conflict_do_nothing(index_elements=["provider", "provider_update_id"])
            )
            await session.execute(statement)
            return (
                await session.scalars(
                    select(InboundEvent.id).where(
                        InboundEvent.provider == message.provider,
                        InboundEvent.provider_update_id == message.provider_update_id,
                    )
                )
            ).one()


class EventWorker:
    def __init__(
        self,
        database: Database,
        redis: Redis,
        encryption: ProfileEncryption,
        flow: ConsentFlow,
        client: ChannelClient,
        *,
        history_provider: SecondContextProvider | None = None,
        history_enabled: bool = False,
    ) -> None:
        self.database = database
        self.redis = redis
        self.encryption = encryption
        self.flow = flow
        self.client = client
        self.history_provider = history_provider
        self.history_enabled = history_enabled

    async def process(self, event_id: UUID) -> None:
        with correlation_scope(internal_job_id=event_id), measurement("worker_dispatch"):
            await self._process(event_id)

    async def _process(self, event_id: UUID) -> None:
        async with self.database.transaction() as session:
            event = await session.get(InboundEvent, event_id)
            if event is None or event.status in TERMINAL or event.user_id is None:
                return
            user_id = event.user_id
        lock = self.redis.lock(
            f"oria:user:{user_id}:conversation-lock",
            timeout=LOCK_SECONDS,
            blocking=False,
            thread_local=False,
        )
        if not await lock.acquire():
            return  # Durable dispatcher will retry; lock contention consumes no attempt.
        claimed = False
        try:
            async with asyncio.timeout(PROCESS_SECONDS):
                if not await self.claim(event_id, user_id):
                    return
                claimed = True
                try:
                    with measurement("worker_process"):
                        await self.calculate(event_id, user_id)
                        await self.finalize(event_id, user_id)
                        await self.deliver(event_id, user_id)
                except Exception as error:
                    await self.failed(event_id, user_id, error)
        except TimeoutError:
            await self.failed(event_id, user_id)
        finally:
            if claimed:
                try:
                    await self.redis.delete(f"oria:event:{event_id}:publication")
                except RedisError:
                    logger.warning("queue_unavailable")
            try:
                await lock.release()  # redis-py uses token-checked Lua; cannot delete a new owner.
            except (LockNotOwnedError, RedisError):
                logger.warning("worker_lock_lost")

    async def locked(
        self, session: AsyncSession, event_id: UUID, user_id: UUID
    ) -> InboundEvent | None:
        # PostgreSQL is the final serialization fence even if Redis is flushed or TTL expires.
        await session.execute(
            select(User).where(User.id == user_id).with_for_update(key_share=True)
        )
        event = await session.scalar(
            select(InboundEvent)
            .where(
                InboundEvent.id == event_id,
                InboundEvent.user_id == user_id,
            )
            .with_for_update()
        )
        return event

    async def claim(self, event_id: UUID, user_id: UUID) -> bool:
        async with self.database.transaction() as session:
            event = await self.locked(session, event_id, user_id)
            if event is None or event.status in TERMINAL:
                return False
            now = datetime.now(UTC)
            if event.expires_at <= now or event.attempts >= MAX_ATTEMPTS:
                await stop_history(
                    session, event, "expired" if event.expires_at <= now else "attempts_exhausted"
                )
                return False
            # A crashed claim becomes eligible after its recovery lease. Pending/ready retry
            # deadlines are enforced by the dispatcher, and below for duplicate job deliveries.
            if event.next_attempt_at > now:
                return False
            earlier = await session.scalar(
                select(
                    exists().where(
                        InboundEvent.user_id == user_id,
                        InboundEvent.sequence < event.sequence,
                        InboundEvent.is_control.is_(True) if event.is_control else true(),
                        InboundEvent.status.not_in(TERMINAL),
                    )
                )
            )
            if earlier:
                return False
            work = await session.get(ConversationHistoryWork, event.id)
            if work is not None and work.phase == "prepared":
                work.cleanup_until = now + REMOTE_PENDING_LIFETIME
            if not event.is_control and await session.scalar(
                select(
                    exists().where(
                        ConversationHistoryWork.user_id == user_id,
                        ConversationHistoryWork.phase == "abandon",
                    )
                )
            ):
                return False
            event.attempts += 1
            event.status = "ready" if event.encrypted_reply is not None else "processing"
            event.next_attempt_at = now + timedelta(seconds=RECOVERY_SECONDS)
            return True

    def decrypt(self, event: InboundEvent, value: bytes, kind: str) -> str:
        assert event.user_id is not None
        return self.encryption.decrypt_event(
            value,
            user_id=event.user_id,
            event_id=event.id,
            kind=kind,
            key_version=event.encryption_key_version,
        )

    async def calculate(self, event_id: UUID, user_id: UUID) -> None:
        # A preparation pass rolls back domain changes, commits only the frozen request,
        # then reruns domain work under a fresh lock in the same bounded queue attempt.
        if await self._calculate(event_id, user_id):
            await self._calculate(event_id, user_id)

    async def _calculate(self, event_id: UUID, user_id: UUID) -> bool:
        async with self.database.transaction() as session:
            event = await self.locked(session, event_id, user_id)
            if event is None or event.status in TERMINAL or event.encrypted_reply is not None:
                return False
            user = await session.get(User, user_id)
            if user is None or user.deleted_at is not None:
                await stop_history(session, event, "user_unavailable")
                return False
            repo = HistoryRepository(session, self.encryption, self.flow.policy_version)
            work = await session.get(ConversationHistoryWork, event_id)
            current = await ConsentRepository(session).current(user_id, self.flow.policy_version)
            enabled = self.history_enabled and (
                self.flow.onboarding is None
                or self.flow.onboarding.context is None
                or self.flow.onboarding.context.enabled
            )
            if work is not None and (not enabled or not await repo.valid(work)):
                await stop_history(session, event, "history_cancelled")
                return False
            if (
                not event.is_control
                and event.admitted_consent_id is not None
                and (current is None or current.id != event.admitted_consent_id)
            ):
                await stop_history(session, event, "consent_changed")
                return False
            attempt = None
            session.info["managed_history_required"] = self.history_enabled
            if enabled and not event.is_control and current is not None:
                if self.history_provider is None:
                    raise ContextUnavailable("Managed history provider unavailable")
                attempt = HistoryAttempt(
                    session,
                    user_id,
                    event_id,
                    self.encryption,
                    self.flow.policy_version,
                    self.history_provider,
                    work,
                )
                session.info["history_attempt"] = attempt
            assert event.encrypted_input is not None
            payload = InputPayload.model_validate_json(
                self.decrypt(event, event.encrypted_input, "input")
            )
            identity = await session.scalar(
                select(SocialIdentity).where(
                    SocialIdentity.user_id == user_id,
                    SocialIdentity.provider == payload.message.provider,
                    SocialIdentity.provider_user_id == payload.message.provider_user_id,
                )
            )
            if identity is None:
                await stop_history(session, event, "user_unavailable")
                return False
            try:
                # A final downstream failure must not commit partial domain mutations.
                async with session.begin_nested():
                    reply = await self.flow.handle_in_session(
                        session,
                        user_id,
                        payload.message,
                        command=payload.command,
                    )
                text, buttons = reply.text, reply.buttons
            except FreezeHistory as freeze:
                # The savepoint has rolled back local learning/projections/clarifications.
                # Only mapping + exact prepared body commit in this transaction.
                await ConversationSessionRepository(
                    session, self.flow.policy_version
                ).get_or_create(user_id)
                mapping = await session.get(ConversationSession, user_id)
                assert mapping is not None
                mapping.session_id, mapping.history_invalidated = (
                    UUID(freeze.prepared.session_id),
                    False,
                )
                await repo.create(event, freeze.prepared)
                return True
            except (AstrologyUnavailable, ContextUnavailable):
                if work is not None or self.history_enabled or event.attempts < MAX_ATTEMPTS:
                    raise
                text, buttons = UNAVAILABLE_REPLY, ()
            if attempt is not None and attempt.accepted is not None:
                if work is None:
                    assert attempt.local_prepared is not None
                    work = await repo.create(event, attempt.local_prepared)
                # Final application adornments (e.g. calculated snapshot label) are
                # part of the exact reply. Mutation receipts are excluded upstream.
                accepted = attempt.accepted.model_copy(update={"assistant_text": text})
                repo.stage(work, accepted)
            elif work is not None:
                await stop_history(session, event, "history_cancelled")
                return False
            consent = await ConsentRepository(session).latest(user_id)
            output = ReplyPayload(
                text=text,
                buttons=buttons,
                chat_id=identity.provider_chat_id,
                policy_version=self.flow.policy_version,
                consent_id=consent.id if consent else None,
            )
            event.encrypted_reply = self.encryption.encrypt_event(
                output.model_dump_json(), user_id=user_id, event_id=event_id, kind="reply"
            )
            event.encryption_key_version = self.encryption.key_version
            event.encrypted_input = None
            event.status = "ready"
            # Domain mutation + encrypted reply + finalization are committed atomically.
            return False

    async def finalize(self, event_id: UUID, user_id: UUID) -> None:
        # Persist ambiguity BEFORE the external mutation; a crash cannot label it unattempted.
        async with self.database.transaction() as session:
            event = await self.locked(session, event_id, user_id)
            work = await session.get(ConversationHistoryWork, event_id)
            if (
                event is None
                or event.status in TERMINAL
                or work is None
                or work.phase == "accepted"
            ):
                return
            repo = HistoryRepository(session, self.encryption, self.flow.policy_version)
            if event.expires_at <= datetime.now(UTC) or not await repo.valid(work):
                await stop_history(session, event, "history_cancelled")
                return
            if work.phase != "finalize" or self.history_provider is None:
                raise ContextUnavailable("History finalization unavailable")
            work.accept_attempted = True
            work.cleanup_until = datetime.now(UTC) + REMOTE_PENDING_LIFETIME
        async with self.database.transaction() as session:
            event = await self.locked(session, event_id, user_id)
            work = await session.get(ConversationHistoryWork, event_id)
            if (
                event is None
                or event.status in TERMINAL
                or work is None
                or work.phase == "accepted"
            ):
                return
            repo = HistoryRepository(session, self.encryption, self.flow.policy_version)
            if event.expires_at <= datetime.now(UTC) or not await repo.valid(work):
                await stop_history(session, event, "history_cancelled")
                return
            assert self.history_provider is not None
            request = repo.finalization(work)
            receipt = await self.history_provider.finalize_history(repo.scope(work), request)
            validate_history_receipt(request, receipt)
            work.receipt, work.phase = receipt.model_dump_json(), "accepted"
            work.encrypted_finalize = None

    async def deliver(self, event_id: UUID, user_id: UUID) -> None:
        previously_ambiguous = False
        async with self.database.transaction() as session:
            event = await self.locked(session, event_id, user_id)
            work = await session.get(ConversationHistoryWork, event_id)
            if event is None or event.status in TERMINAL:
                return
            if work is not None:
                if work.phase != "accepted":
                    return
                # A later explicit rejection cannot disprove an earlier ambiguous send.
                previously_ambiguous = work.delivery == "unknown"
                # A timeout/crash after sending is ambiguous even if the DB transaction rolls back.
                work.delivery = "unknown"
        try:
            await self._deliver(event_id, user_id)
        except Exception as error:
            from oria_engine.domain.channel import DeliveryRejected

            if isinstance(error, DeliveryRejected) and not previously_ambiguous:
                async with self.database.transaction() as session:
                    event = await self.locked(session, event_id, user_id)
                    work = await session.get(ConversationHistoryWork, event_id)
                    if event is not None and event.status not in TERMINAL and work is not None:
                        work.delivery = "failed"
            raise

    async def _deliver(self, event_id: UUID, user_id: UUID) -> None:
        async with self.database.transaction() as session:
            event = await self.locked(session, event_id, user_id)
            if event is None or event.status in TERMINAL:
                return
            user = await session.get(User, user_id)
            if user is None or user.deleted_at is not None:
                await stop_history(session, event, "user_unavailable")
                return
            if event.expires_at <= datetime.now(UTC):
                await stop_history(session, event, "expired")
                return
            assert event.encrypted_reply is not None
            output = ReplyPayload.model_validate_json(
                self.decrypt(event, event.encrypted_reply, "reply")
            )
            consent = await ConsentRepository(session).latest(user_id)
            if output.policy_version != self.flow.policy_version or output.consent_id != (
                consent.id if consent else None
            ):
                await stop_history(session, event, "consent_changed")
                return
            work = await session.get(ConversationHistoryWork, event_id)
            if work is not None:
                repo = HistoryRepository(session, self.encryption, self.flow.policy_version)
                if work.phase != "accepted" or not await repo.valid(work):
                    await stop_history(session, event, "history_cancelled")
                    return
            await self.client.send_text(output.chat_id, output.text, buttons=output.buttons)
            if work is not None:
                work.phase, work.delivery = "terminal", "sent"
                work.encrypted_prepared = work.encrypted_finalize = None
            terminal(event, "sent")
            # A crash after send may duplicate a reply, never the domain mutation.

    async def failed(self, event_id: UUID, user_id: UUID, error: Exception | None = None) -> None:
        async with self.database.transaction() as session:
            event = await self.locked(session, event_id, user_id)
            if event is None or event.status in TERMINAL:
                return
            if (
                event.attempts >= MAX_ATTEMPTS
                or isinstance(error, HistoryFailure)
                and not error.retryable
            ):
                await stop_history(
                    session,
                    event,
                    error.code if isinstance(error, HistoryFailure) else "attempts_exhausted",
                )
                if isinstance(error, HistoryFailure) and error.code == "session_deleted":
                    mapping = await session.get(ConversationSession, user_id)
                    if mapping is not None:
                        mapping.history_invalidated = True
                count("worker_dead")
                logger.error("worker_dead")
            else:
                event.status = "ready" if event.encrypted_reply is not None else "pending"
                event.failure_code = "processing_failed"
                event.next_attempt_at = datetime.now(UTC) + timedelta(
                    seconds=min(5 * 2**event.attempts, 120)
                )
                count("worker_retry")
                logger.warning("worker_retry")


async def recoverable(database: Database) -> list[UUID]:
    """Bounded scan; Redis loss or an enqueue/crash gap cannot strand canonical work."""
    async with database.transaction() as session:
        now = datetime.now(UTC)
        await session.execute(
            delete(TemporalClarification).where(TemporalClarification.expires_at <= now)
        )
        await session.execute(delete(KnowledgeDialogue).where(KnowledgeDialogue.expires_at <= now))
        expired = (
            await session.scalars(
                select(InboundEvent)
                .where(
                    InboundEvent.status.not_in(TERMINAL),
                    InboundEvent.expires_at <= now,
                )
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        ).all()
        for event in expired:
            await stop_history(session, event, "expired")
        await session.flush()
        return list(
            await session.scalars(
                select(InboundEvent.id)
                .join(User, InboundEvent.user_id == User.id)
                .where(
                    InboundEvent.status.not_in(TERMINAL),
                    InboundEvent.next_attempt_at <= now,
                    dispatch_head(),
                )
                .order_by(InboundEvent.sequence)
                .limit(100)
            )
        )
