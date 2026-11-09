"""Payload-free abandonment runs without Redis, current consent or capture enablement."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from oria_engine.context.contracts import ContextUnavailable
from oria_engine.context.history import Abandon, HistoryFailure
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.db.history import HistoryRepository, stop_history
from oria_engine.db.models import ConversationHistoryWork, InboundEvent
from oria_engine.db.repositories import UserRepository
from oria_engine.db.session import Database
from oria_engine.privacy.encryption import ProfileEncryption


async def recover_history(
    database: Database,
    encryption: ProfileEncryption,
    policy: str,
    provider: SecondContextProvider,
    *,
    enabled: bool,
) -> None:
    async with database.transaction() as session:
        ids = list(
            await session.execute(
                select(ConversationHistoryWork.event_id, ConversationHistoryWork.user_id)
                .where(ConversationHistoryWork.phase != "terminal")
                .order_by(ConversationHistoryWork.next_cleanup_at)
                .limit(4)
            )
        )
    for event_id, user_id in ids:
        async with database.transaction() as session:
            if await UserRepository(session).get(user_id, for_update=True) is None:
                continue  # Account erasure owns this lifecycle under its permanent fence.
            event = await session.get(InboundEvent, event_id)
            work = await session.get(ConversationHistoryWork, event_id)
            if event is None or work is None or work.phase == "terminal":
                continue
            now = datetime.now(UTC)
            repo = HistoryRepository(session, encryption, policy)
            if work.phase != "abandon" and (
                event.expires_at <= now
                or event.status in {"sent", "dead"}
                or (not enabled and work.phase == "prepared")
                or not await repo.valid(work)
            ):
                await stop_history(session, event, "history_cancelled")
            if work.phase != "abandon":
                work.next_cleanup_at = now + timedelta(seconds=60)
                continue
        # Cancellation and payload erasure commit before any abandonment call.
        async with database.transaction() as session:
            if await UserRepository(session).get(user_id, for_update=True) is None:
                continue
            work = await session.get(ConversationHistoryWork, event_id)
            if work is None or work.phase != "abandon":
                continue
            now = datetime.now(UTC)
            if work.cleanup_until <= now:
                work.phase = "terminal"
                continue
            if work.next_cleanup_at > now:
                continue
            request = Abandon(
                contract_version=1,
                user=provider.subject(user_id),
                session_id=str(work.session_id),
                turn_id=event_id,
                action="abandon",
            )
            try:
                receipt = await provider.finalize_history(repo.scope(work), request)
                work.receipt, work.phase = receipt.model_dump_json(), "terminal"
            except HistoryFailure as error:
                if error.code in {
                    "turn_not_found",
                    "session_not_found",
                    "turn_abandoned",
                    "turn_expired",
                    "session_deleted",
                    "subject_deleted",
                }:
                    work.phase = "terminal"
                # A conflict can mean already accepted. Preserve that uncertainty;
                # never reinterpret it as a successful abandonment or erase remote history.
            except ContextUnavailable:
                pass
            work.next_cleanup_at = now + timedelta(seconds=60)
