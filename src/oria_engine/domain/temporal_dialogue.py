"""Application-owned temporal clarification, separate from long-term event learning."""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.astrology.contracts import WireModel
from oria_engine.db.birth_profiles import BirthProfileRepository
from oria_engine.db.models import BirthProfile
from oria_engine.db.temporal import PendingTemporal, TemporalRepository
from oria_engine.domain.active import route_active
from oria_engine.domain.birth_time import birth_zone
from oria_engine.domain.temporal import (
    SUFFIX_CLOCK,
    EventAnchor,
    TemporalAnalysis,
    TemporalMention,
    analyze_temporal,
)
from oria_engine.knowledge.contracts import CalendarDate, PartialDate, RecordRef, TemporalEvidence
from oria_engine.privacy.encryption import ProfileEncryption
from oria_engine.privacy.messages import held_birth_spans, prepare_active_input


class TemporalDialogue(WireModel):
    text: str
    reference: datetime
    timezone: str | None
    timezone_source: Literal["explicit_event", "current_preference"] = "current_preference"
    analysis: TemporalAnalysis
    anchors: tuple[EventAnchor, ...]
    unresolved: TemporalMention | None = None
    selected_record: RecordRef | None = None
    source_update_id: str = ""
    operation_source: UUID | None = None

    def model_text(self) -> str:
        """No birth candidates/anchor dates or saved timezone metadata are forwarded."""
        filtered = prepare_active_input(self.text)
        held = held_birth_spans(self.text)
        notes = []
        for mention in self.analysis.mentions:
            if any(start <= mention.start < end for start, end in held):
                continue
            if mention.role in {"birth_input", "profile_correction"} or (
                mention.anchor_label and re.search(r"birthday|born", mention.anchor_label)
            ):
                continue
            if mention.issue is None and mention.evidence.value is not None:
                notes.append(mention.evidence.value.model_dump_json())
        suffix = (
            "\nResolved date context (user-stated, not astrology facts or saved events): "
            + "; ".join(notes)
        )
        return filtered + suffix if notes and len(filtered + suffix) <= 4096 else filtered


def _resume(
    pending: PendingTemporal, reply: str
) -> tuple[str, str | None, tuple[EventAnchor, ...]] | None:
    """Only a bounded answer to the pending question continues it; other chat starts fresh."""
    mention = pending.unresolved
    if mention is None or mention.issue is None:
        return None
    value = reply.strip()
    if value.startswith("/timezone "):
        value = value.split(maxsplit=1)[1]
    if mention.issue == "timezone":
        try:
            birth_zone(value)
        except (KeyError, ValueError):
            if re.fullmatch(r"[A-Za-z_+-]+/[A-Za-z_+/-]+|[A-Z]{2,5}", value):
                return pending.text, pending.timezone, pending.anchors
            return None
        return pending.text, value, pending.anchors
    original = pending.text[mention.start : mention.end]
    replacement = None
    anchors = pending.anchors
    if mention.issue == "year" and re.fullmatch(
        r"(?:in )?\d{4}|(?:this|next|last) year", value, re.I
    ):
        replacement = (
            original + " " + ("in " + value if value.isdigit() and mention.anchor_label else value)
        )
    elif mention.issue == "leap_day" and re.fullmatch(
        r"(?:February 28|March 1)(?:st|th)?", value, re.I
    ):
        observance = "february_28" if value.casefold().startswith("february") else "march_1"
        anchors = tuple(
            a.model_copy(update={"leap_day_observance": observance})
            if a.label.casefold() == mention.anchor_label
            else a
            for a in anchors
        )
        replacement = original
    elif mention.issue == "clock" and re.fullmatch(
        r"(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm)?", value, re.I
    ):
        replacement = (
            re.sub(r"\s+at\s*$", "", SUFFIX_CLOCK.sub("", original))
            + " at "
            + re.sub(r"^at\s+", "", value, flags=re.I)
        )
    elif mention.issue in {"anchor", "date"}:
        parsed = analyze_temporal(
            value, received_at=pending.reference_time_utc, current_timezone=pending.timezone
        )
        if len(parsed.mentions) == 1:
            candidate = parsed.mentions[0]
            if candidate.issue and candidate.start == 0 and candidate.end == len(value):
                return pending.text, pending.timezone, pending.anchors
            if candidate.issue is None and candidate.start == 0 and candidate.end == len(value):
                if (
                    mention.issue == "anchor"
                    and mention.anchor_label
                    and isinstance(candidate.evidence.value, CalendarDate)
                ):
                    anchors = (
                        *anchors,
                        EventAnchor(
                            label=mention.anchor_label,
                            day=candidate.evidence.value.value,
                            recurring="birthday" in mention.anchor_label
                            or "anniversary" in mention.anchor_label,
                        ),
                    )
                    replacement = original
                elif mention.issue == "date":
                    replacement = value
    if replacement is None:
        return None
    text = pending.text[: mention.start] + replacement + pending.text[mention.end :]
    # A dangling 'at' belongs to the pending date, not to the next message.
    text = re.sub(r"\bat\s+at\b", "at", text, flags=re.I)
    return text, pending.timezone, anchors


async def prepare_temporal_dialogue(
    session: AsyncSession,
    user_id: UUID,
    *,
    encryption: ProfileEncryption,
    policy_version: str,
    consent_id: UUID,
    text: str,
    received_at: datetime,
    source_update_id: str,
    timezone: str | None,
    saved_anchors: tuple[EventAnchor, ...] = (),
    selected_record: RecordRef | None = None,
    operation_source: UUID | None = None,
    timezone_source: Literal["explicit_event", "current_preference"] = "current_preference",
) -> TemporalDialogue:
    repository = TemporalRepository(session, encryption, policy_version)
    pending = await repository.get(user_id)
    anchors: tuple[EventAnchor, ...] = saved_anchors
    if pending is not None:
        resumed = _resume(pending, text)
        if resumed is not None:
            text, timezone, pending_anchors = resumed
            anchors = (*saved_anchors, *(a for a in pending_anchors if a.reference is None))
            received_at = pending.reference_time_utc
            source_update_id = pending.source_update_id
            selected_record = pending.selected_record or selected_record
            operation_source = pending.operation_source or operation_source
            timezone_source = (
                "explicit_event"
                if pending.unresolved is not None and pending.unresolved.issue == "timezone"
                else pending.timezone_source
            )
        elif text == pending.text and source_update_id == pending.source_update_id:
            received_at, timezone, pending_anchors = (
                pending.reference_time_utc,
                pending.timezone,
                pending.anchors,
            )
            anchors = (*saved_anchors, *(a for a in pending_anchors if a.reference is None))
            timezone_source = pending.timezone_source
        await repository.clear(user_id)
    # Only an explicit own-birth anchor authorizes reading these local inputs.
    # Natal interpretations and volunteered partner dates still use only derived facts.
    if re.search(r"\b(?:my birthday|the day I was born)\b", text, re.I) and not re.search(
        r"\b(?:my birthday (?:is|was)|I was born (?:on|in))\b", text, re.I
    ):
        profile = await BirthProfileRepository(
            session, encryption, policy_version=policy_version
        ).get(user_id)
        if profile is not None:
            row = await session.scalar(select(BirthProfile).where(BirthProfile.user_id == user_id))
            assert row is not None
            reference = RecordRef(kind="event", id=row.id, revision=row.revision)
            own = (
                EventAnchor(
                    label="my birthday", day=profile.birth_date, recurring=True, reference=reference
                ),
                EventAnchor(
                    label="the day I was born", day=profile.birth_date, reference=reference
                ),
            )
            anchors = (
                *anchors,
                *(a for a in own if a.label not in {item.label for item in anchors}),
            )
    analysis = analyze_temporal(
        text,
        received_at=received_at,
        current_timezone=timezone,
        anchors=anchors,
        timezone_source=timezone_source,
    )
    from oria_engine.domain.memory import directive

    memory_request = directive(text)
    if memory_request is not None and memory_request.action == "correct":
        # In “correct our wedding to May 2, not May 1”, the record selector
        # and quoted old value are not replacement dates or calculation targets.
        replacement = re.search(r"\bto\s+", text, re.I)
        start = replacement.end() if replacement else 0
        old_value = re.search(r"\bnot\b", text[start:], re.I)
        end = start + old_value.start() if old_value else len(text)
        analysis = analysis.model_copy(
            update={"mentions": tuple(m for m in analysis.mentions if start <= m.start < end)}
        )
    unresolved = next((m for m in analysis.mentions if m.issue is not None), None)
    initial_intent = route_active(
        text, received_at=received_at, current_timezone=timezone, anchors=anchors
    )
    if initial_intent.kind == "current_transits":
        unresolved = None  # Legacy today/now samples ingress without a timezone.
    if unresolved is None:
        intent = initial_intent
        if intent.kind in {"clarify_date", "clarify_timezone"}:
            if len(analysis.mentions) == 1:
                mention = analysis.mentions[0]
                value = mention.evidence.value
                issue = "timezone" if intent.kind == "clarify_timezone" else "date"
                if (
                    isinstance(value, PartialDate)
                    and value.year is None
                    and value.month
                    and value.day
                ):
                    issue = "year"
                unresolved = mention.model_copy(update={"issue": issue})
            else:
                start = analysis.mentions[0].start if analysis.mentions else 0
                end = analysis.mentions[-1].end if analysis.mentions else len(text)
                unresolved = TemporalMention(
                    start=start,
                    end=end,
                    role="target",
                    evidence=TemporalEvidence(
                        expression=text[start:end],
                        reference_time_utc=received_at,
                        resolution_version="english-gregorian-2",
                    ),
                    issue="timezone" if intent.kind == "clarify_timezone" else "date",
                )
    # No-retention language is respected for this additional temporary state.
    if unresolved is not None and not re.search(
        r"\b(?:don['’]t|do not|never) (?:remember|save|store)\b", text, re.I
    ):
        await repository.save(
            user_id,
            PendingTemporal(
                consent_id=consent_id,
                text=text,
                reference_time_utc=received_at,
                timezone=timezone,
                timezone_source=timezone_source,
                anchors=tuple(a for a in anchors if a.reference is None)[:32],
                unresolved=unresolved,
                source_update_id=source_update_id,
                selected_record=selected_record,
                operation_source=operation_source,
            ),
        )
    return TemporalDialogue(
        text=text,
        reference=received_at,
        timezone=timezone,
        timezone_source=timezone_source,
        anchors=anchors,
        analysis=analysis,
        unresolved=unresolved,
        selected_record=selected_record,
        source_update_id=source_update_id,
        operation_source=operation_source,
    )
