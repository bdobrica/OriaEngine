"""Synthetic conversation-history release check using the released Oria HTTP adapter.

Run inside the worker with private settings. --generate additionally calls the
configured model and checks recall of two random synthetic codes. No Telegram send,
canonical account mutation, transcript, identifier or credential is printed.
Only fresh synthetic subjects are used and purged, including on failure.
"""

import argparse
import asyncio
import os
from pathlib import Path
from uuid import UUID, uuid4

from oria_engine.config import Settings
from oria_engine.context.contracts import ContextScope, ConversationRequest
from oria_engine.context.history import (
    AcceptGenerated,
    AcceptLocal,
    HistoryFailure,
    HistoryRecordRef,
)
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.knowledge.contracts import (
    ContextProjection,
    ProjectionDelete,
    ProjectionUpsert,
)


async def check(
    provider: SecondContextProvider, *, generate: bool, owner: UUID | None = None
) -> None:
    owner = owner or uuid4()
    scope = ContextScope(user_id=owner, session_id=uuid4())
    subject = provider.subject(owner)
    source = HistoryRecordRef(kind="event", id=uuid4(), revision=1)
    code = uuid4().hex
    local = AcceptLocal(
        contract_version=1,
        user=subject,
        session_id=str(scope.session_id),
        turn_id=uuid4(),
        action="accept_local",
        user_text="Choose a synthetic code for this conversation.",
        assistant_text=f"Synthetic code: {code}",
        knowledge_refs=(source,),
    )
    stage = "capability discovery"
    try:
        capabilities = await provider.history_capabilities(owner, refresh=True)
        # This is the recent-only release gate. Adaptive requires separate evaluation.
        assert set(capabilities.history_modes) == {"off", "recent"}
        await provider.projection_capabilities(owner)
        stage = "source linking and idempotent local acceptance"
        await provider.project(
            ProjectionUpsert(
                user=subject,
                operation_id=uuid4(),
                projection=ContextProjection(
                    record=source,
                    label="Synthetic release event",
                    summary="A synthetic conversation continuity check.",
                    knowledge_kind="user_statement",
                    sources=(source,),
                ),
            )
        )
        receipt = await provider.finalize_history(scope, local)
        assert receipt == await provider.finalize_history(scope, local)
        assert receipt.sequence == 1
        if generate:
            stage = "configured provider continuity and accepted replacement"
            # Each next question omits the random code. Only eligible replay supplies it.
            for sequence in (2, 3):
                prepared = provider.prepare_history_turn(
                    scope,
                    ConversationRequest(
                        filtered_message=(
                            "What is the latest synthetic code in this conversation? "
                            "Reply with only that code, without punctuation or explanation."
                        ),
                        knowledge_refs=(source,),
                    ),
                    turn_id=uuid4(),
                )
                draft = await provider.respond_history(scope, prepared)
                assert draft.text.strip() == code
                assert draft == await provider.respond_history(scope, prepared)
                code = uuid4().hex
                accepted = AcceptGenerated(
                    contract_version=1,
                    user=subject,
                    session_id=str(scope.session_id),
                    turn_id=prepared.turn_id,
                    action="accept_generated",
                    response_id=draft.response_id,
                    assistant_text=f"Synthetic code: {code}",
                )
                receipt = await provider.finalize_history(scope, accepted)
                assert receipt.sequence == sequence
                assert receipt == await provider.finalize_history(scope, accepted)

        stage = "whole linked-session erasure and delayed retry rejection"
        deletion = ProjectionDelete(
            user=subject,
            operation_id=uuid4(),
            record=source.model_copy(update={"revision": 2}),
        )
        await provider.project(deletion)
        await provider.project(deletion)
        try:
            await provider.finalize_history(scope, local)
        except HistoryFailure as error:
            assert error.code == "session_deleted"
        else:
            raise AssertionError("Deleted session accepted a delayed retry")

        stage = "independent accepted history and full subject purge"
        independent = ContextScope(user_id=owner, session_id=uuid4())
        unlinked = local.model_copy(
            update={"session_id": str(independent.session_id), "knowledge_refs": ()}
        )
        await provider.finalize_history(independent, unlinked)
        await provider.purge(owner)
        await provider.purge(owner)
        try:
            await provider.finalize_history(independent, unlinked)
        except HistoryFailure as error:
            assert error.code == "subject_deleted"
        else:
            raise AssertionError("Purged subject accepted a delayed retry")
    except Exception:
        raise RuntimeError(
            f"History release check failed during {stage}; payloads withheld"
        ) from None
    finally:
        try:
            await provider.purge(owner)
        except Exception:
            raise RuntimeError(
                "Synthetic subject cleanup incomplete; retry purge privately"
            ) from None
    print("PASS: recent capability, accepted receipts, selective erasure and full purge")
    if generate:
        print("PASS: configured model recalled local and accepted replacement dialogue")


async def main(generate: bool, journal: Path, *, cleanup_only: bool = False) -> None:
    # The operator mounts a protected durable directory. Keep the fresh owner UUID
    # before any HTTP call so even a crash/failed cleanup can be recovered privately.
    if cleanup_only:
        owner = UUID(journal.read_text().strip())
    else:
        owner = uuid4()
        descriptor = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(str(owner))
            handle.flush()
            os.fsync(handle.fileno())
    provider = SecondContextProvider(Settings())
    try:
        if cleanup_only:
            await provider.purge(owner)
            print("PASS: pending synthetic subject purged")
        else:
            await check(provider, generate=generate, owner=owner)
        journal.unlink()
    finally:
        await provider.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true", help="also call the configured model")
    parser.add_argument("--cleanup-journal", type=Path, required=True, help="private durable file")
    parser.add_argument("--cleanup-only", action="store_true", help="purge the journaled subject")
    args = parser.parse_args()
    if args.generate and args.cleanup_only:
        parser.error("--generate and --cleanup-only are mutually exclusive")
    asyncio.run(main(args.generate, args.cleanup_journal, cleanup_only=args.cleanup_only))
