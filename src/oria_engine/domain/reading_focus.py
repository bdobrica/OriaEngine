"""Bounded local reading handoff; no transcript, chart cache or model-selected tool."""

import re
from datetime import datetime
from uuid import UUID

from oria_engine.db.knowledge import KnowledgeRepository, MemoryProgress, ReadingFocus

# Whole-message matching avoids treating a new named topic/date as a continuation.
FOLLOW_UP = re.compile(
    r"(?:please )?(?:"
    r"what does (?:it|that|this)(?: all)? mean|"
    r"(?:can|could|would) you explain (?:it|that|this)|"
    r"explain (?:it|that|this)(?: to me)?|"
    r"tell me more(?: about (?:it|that|this))?|"
    r"(?:say|put) (?:it|that|this)|"
    r"make (?:it|that|this) (?:simpler|shorter|clearer)|"
    r"how so|why|go on"
    r")(?: in (?:plain English|simple(?:r)? (?:words|terms)|everyday language))?"
    r"(?: please)?[.!?]*",
    re.I,
)


async def take_reading_focus(
    repository: KnowledgeRepository, user_id: UUID, text: str
) -> ReadingFocus | None:
    progress = await repository.progress(user_id)
    if progress is None or progress.reading is None or progress.action is not None:
        return None
    # A new topic consumes the old reading selector. A successful continuation
    # replaces it after recalculation; failed transactions preserve the old state.
    await repository.set_progress(user_id, progress.model_copy(update={"reading": None}))
    return progress.reading if FOLLOW_UP.fullmatch(text.strip()) else None


async def keep_reading_focus(
    repository: KnowledgeRepository,
    user_id: UUID,
    focus: ReadingFocus,
    reference: datetime,
) -> None:
    progress = await repository.progress(user_id)
    if progress is not None and progress.action is not None:
        return
    if progress is None:
        progress = MemoryProgress(
            consent_id=await repository.lock(user_id), reference_time_utc=reference
        )
    # Preserve CRUD focus independently: "forget that" must not suddenly include
    # the user's own birth merely because it is a calculation dependency.
    await repository.set_progress(
        user_id, progress.model_copy(update={"reading": focus, "reference_time_utc": reference})
    )
