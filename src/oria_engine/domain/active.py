"""Deterministic active routing and calculated-fact replies; no LLM authority."""

import asyncio
import re
from datetime import UTC, date, datetime, time
from typing import Literal, Self

from pydantic import model_validator

from oria_engine.astrology.client import AstrologyClient, AstrologyUnavailable
from oria_engine.astrology.contracts import NatalResult, WireModel
from oria_engine.astrology.transits import TransitRequest, TransitResult, validate_target
from oria_engine.domain.birth_time import birth_zone
from oria_engine.domain.policy import SAFETY_REPLY, is_harmful_request
from oria_engine.domain.relative_time import (
    HINT,
    TimeClarification,
    TimezoneRequired,
    resolve_relative,
)
from oria_engine.domain.temporal import (
    MONTH_PATTERN,
    READING,
    EventAnchor,
    analyze_temporal,
    clarification,
)
from oria_engine.knowledge.contracts import CalendarDate, DateInterval, Instant

IntentKind = Literal[
    "natal_explanation",
    "current_transits",
    "transits_for_date",
    "follow_up",
    "unsupported_high_stakes",
    "clarify_date",
    "clarify_timezone",
]


class ActiveIntent(WireModel):
    kind: IntentKind
    target_timestamp_utc: datetime | None = None
    clarification_text: str | None = None

    @model_validator(mode="after")
    def valid_target(self) -> Self:
        needs_target = self.kind in {"current_transits", "transits_for_date"}
        if needs_target != (self.target_timestamp_utc is not None):
            raise ValueError("Only transit intents require a target")
        if self.target_timestamp_utc is not None:
            validate_target(self.target_timestamp_utc)
        return self


ISO_DATE = re.compile(r"(?<![\w-])\d{4}-\d{2}-\d{2}(?![\w-])")
DATE_HINT = re.compile(
    r"\d[\d\s./:-]*\d|\b(date|tomorrow|yesterday|tonight|week|month|year|"
    r"next|last|ago|morning|evening|afternoon|noon|midnight|spring|summer|autumn|winter|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
    re.IGNORECASE,
)
CURRENT = re.compile(r"\b(today|now|current(?:ly)?)\b", re.IGNORECASE)
NATAL = re.compile(
    r"\b(natal|birth\s+chart|chart|ascendant|rising|midheaven|sun|moon|mercury|venus|"
    r"mars|jupiter|saturn|uranus|neptune|pluto|houses?)\b",
    re.IGNORECASE,
)


def route_active(
    text: str,
    *,
    received_at: datetime,
    current_timezone: str | None = None,
    anchors: tuple[EventAnchor, ...] = (),
) -> ActiveIntent:
    """English demo grammar. Unrecognized language never authorizes a tool call."""
    if is_harmful_request(text):
        return ActiveIntent(kind="unsupported_high_stakes")
    if received_at.utcoffset() is None:
        raise ValueError("Message time must be timezone aware")
    analysis = analyze_temporal(
        text, received_at=received_at, current_timezone=current_timezone, anchors=anchors
    )
    if (
        not analysis.mentions
        and not re.search(r"\d", text)
        and not HINT.search(text)
        and not READING.search(text)
    ):
        return ActiveIntent(kind="natal_explanation" if NATAL.search(text) else "follow_up")
    targets = [m for m in analysis.mentions if m.role == "target"]
    if not targets and any(isinstance(m.evidence.value, DateInterval) for m in analysis.mentions):
        return ActiveIntent(kind="follow_up")
    if not analysis.narrative and not targets and len(analysis.mentions) == 1:
        mention = analysis.mentions[0]
        if re.search(
            MONTH_PATTERN + r"|this day (?:last|next) year|\bat\s+\d",
            mention.evidence.expression,
            re.I,
        ):
            targets = [mention]
    # Volunteered events never turn into tool requests just because they have dates.
    if not targets and (
        analysis.narrative
        or any(
            m.role in {"birth_input", "profile_correction", "life_event", "anniversary"}
            for m in analysis.mentions
        )
    ):
        return ActiveIntent(kind="follow_up")
    if targets or any(m.anchor_label for m in analysis.mentions):
        candidates = targets or list(analysis.mentions)
        if len(candidates) != 1:
            return ActiveIntent(kind="clarify_date")
        mention = candidates[0]
        if mention.issue:
            return ActiveIntent(
                kind="clarify_timezone" if mention.issue == "timezone" else "clarify_date",
                clarification_text=clarification(mention.issue),
            )
        if mention.role not in {"target", "context"}:
            return ActiveIntent(kind="follow_up")
        temporal = mention.evidence.value
        if mention.evidence.expression.casefold() in {"today", "now"}:
            return ActiveIntent(
                kind="current_transits", target_timestamp_utc=received_at.astimezone(UTC)
            )
        if not mention.anchor_label:
            try:
                legacy = resolve_relative(
                    mention.evidence.expression, received_at, mention.evidence.timezone
                )
                if legacy is not None:
                    return ActiveIntent(kind="transits_for_date", target_timestamp_utc=legacy)
            except (TimeClarification, ValueError, OverflowError):
                pass
        if isinstance(temporal, Instant):
            try:
                return ActiveIntent(kind="transits_for_date", target_timestamp_utc=temporal.value)
            except ValueError:
                return ActiveIntent(kind="clarify_date")
        if isinstance(temporal, CalendarDate):
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", mention.evidence.expression):
                target = datetime.combine(temporal.value, time(12), tzinfo=UTC)
            elif mention.evidence.timezone is None:
                return ActiveIntent(
                    kind="clarify_timezone", clarification_text=clarification("timezone")
                )
            else:
                target = datetime.combine(
                    temporal.value, time(12), tzinfo=birth_zone(mention.evidence.timezone)
                ).astimezone(UTC)
            try:
                return ActiveIntent(kind="transits_for_date", target_timestamp_utc=target)
            except ValueError:
                return ActiveIntent(kind="clarify_date")
        if temporal is not None and temporal.kind == "local_datetime":
            return ActiveIntent(
                kind="clarify_timezone", clarification_text=clarification("timezone")
            )
        return ActiveIntent(
            kind="clarify_date",
            clarification_text=(
                "Which single date and time should I sample? A date range needs more than "
                "the available single-instant calculation."
            ),
        )
    # Keep published v1 snapshot conventions for the existing date-only grammar.
    dates = ISO_DATE.findall(text)
    remainder = ISO_DATE.sub("", text)
    if not dates and (DATE_HINT.search(text) or HINT.search(text)):
        try:
            relative_target = resolve_relative(text, received_at, current_timezone)
            if relative_target is not None:
                return ActiveIntent(kind="transits_for_date", target_timestamp_utc=relative_target)
        except TimezoneRequired:
            return ActiveIntent(kind="clarify_timezone")
        except (TimeClarification, ValueError, OverflowError):
            return ActiveIntent(kind="clarify_date")
    if dates or DATE_HINT.search(text):
        # Reject multiple dates, other date/time hints and mixed relative/absolute targets.
        if (
            len(dates) == 1
            and not CURRENT.search(text)
            and not re.search(r"\d", remainder)
            and not DATE_HINT.search(re.sub(r"\bdate\b", "", remainder, flags=re.IGNORECASE))
        ):
            try:
                target = datetime.combine(date.fromisoformat(dates[0]), time(12), tzinfo=UTC)
                return ActiveIntent(kind="transits_for_date", target_timestamp_utc=target)
            except ValueError:
                pass
        if len(analysis.mentions) == 1:
            mention = analysis.mentions[0]
            if ISO_DATE.fullmatch(mention.evidence.expression):
                return ActiveIntent(kind="clarify_date")
            if mention.issue:
                return ActiveIntent(
                    kind="clarify_timezone" if mention.issue == "timezone" else "clarify_date",
                    clarification_text=clarification(mention.issue),
                )
            temporal = mention.evidence.value
            if isinstance(temporal, CalendarDate):
                if current_timezone is None:
                    return ActiveIntent(
                        kind="clarify_timezone", clarification_text=clarification("timezone")
                    )
                try:
                    target = datetime.combine(
                        temporal.value, time(12), tzinfo=birth_zone(current_timezone)
                    ).astimezone(UTC)
                    return ActiveIntent(kind="transits_for_date", target_timestamp_utc=target)
                except ValueError:
                    pass
        return ActiveIntent(kind="clarify_date")
    if CURRENT.search(text) or re.search(r"\btransits?\b", text, re.IGNORECASE):
        if re.search(r"\d", text):
            return ActiveIntent(kind="clarify_date")
        if received_at.utcoffset() is None:
            raise ValueError("Message time must be timezone aware")
        return ActiveIntent(
            kind="current_transits", target_timestamp_utc=received_at.astimezone(UTC)
        )
    if NATAL.search(text):
        return ActiveIntent(kind="natal_explanation")
    return ActiveIntent(kind="follow_up")


class ActiveFacts(WireModel):
    intent: ActiveIntent
    natal: NatalResult | None = None
    transits: TransitResult | None = None


async def prepare_active(
    text: str,
    *,
    received_at: datetime,
    natal: NatalResult,
    client: AstrologyClient,
    current_timezone: str | None = None,
    intent: ActiveIntent | None = None,
) -> ActiveFacts:
    """Accept only the caller's consent-scoped, current derived cache, never raw profile data."""
    intent = intent or route_active(
        text, received_at=received_at, current_timezone=current_timezone
    )
    if intent.kind == "natal_explanation":
        return ActiveFacts(intent=intent, natal=natal)
    if intent.target_timestamp_utc is not None:
        request = TransitRequest.from_natal(natal, intent.target_timestamp_utc)
        try:
            async with asyncio.timeout(20):
                result = TransitResult.model_validate(await client.calculate_transits(request))
            if (
                result.birth_time_accuracy != request.birth_time_accuracy
                or result.target_timestamp_utc != request.target_timestamp_utc
            ):
                raise AstrologyUnavailable()
        except Exception:
            raise AstrologyUnavailable("Transit calculation temporarily unavailable") from None
        return ActiveFacts(intent=intent, transits=result)
    return ActiveFacts(intent=intent)


def render_active(facts: ActiveFacts) -> str:
    """Bounded factual demo output until the persona/policy/LLM stages are connected."""
    if facts.intent.kind == "unsupported_high_stakes":
        return SAFETY_REPLY
    if facts.intent.clarification_text:
        return facts.intent.clarification_text
    if facts.intent.kind == "clarify_timezone":
        return (
            "Which timezone should I use for your day? Set it with /timezone Europe/Bucharest "
            "(use your own IANA timezone), then resend your question. "
            "Your current timezone can differ from your birthplace."
        )
    if facts.intent.kind == "clarify_date":
        return (
            "Please choose one time: for example tomorrow, in 3 hours, next Friday, "
            "or YYYY-MM-DD (1800–2399). Set /timezone for local dates. "
            "For a local clock time, try tomorrow at 15:30. I calculate a snapshot, "
            "not a forecast covering a whole period. Clock-change times may need clarification."
        )
    if facts.intent.kind == "follow_up":
        return (
            "For this demo, ask about your natal chart, transits today, or transits on "
            "YYYY-MM-DD. Please restate the topic for a follow-up; conversational "
            "interpretation isn't connected yet."
        )
    chart = facts.transits or facts.natal
    assert chart is not None
    lines = ["Calculated astrology facts — interpretive, not a scientific forecast."]
    if facts.transits is not None:
        lines.append(
            "Transit snapshot: "
            + facts.transits.target_timestamp_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
            + (
                " (one resolved instant; ISO date-only requests use noon UTC)."
                if facts.intent.kind == "transits_for_date"
                else " (message time, not a local-day forecast)."
            )
        )
    else:
        lines.append("Your saved natal chart:")
    if chart.birth_time_accuracy == "approximate":
        lines.append("Natal references use your approximate birth time and are uncertain.")
    if chart.birth_time_accuracy == "unknown":
        lines.append(
            "Birth time is unknown: natal positions, houses, angles and aspects are unavailable."
        )
        if facts.transits is not None:
            lines.append("These transiting positions are general, not personalized natal aspects.")
    for p in chart.planets:
        lines.append(
            f"{p.body.title()}: {p.degree_in_sign:.2f}° {p.sign}"
            + ("; retrograde" if p.retrograde else "")
            + (f"; house {p.house}" if p.house is not None else "")
        )
    if facts.natal is not None:
        if facts.natal.angles is not None:
            lines.append(
                f"Ascendant: {facts.natal.angles.ascendant:.2f}°; "
                f"MC: {facts.natal.angles.midheaven:.2f}° (ecliptic longitude)."
            )
        elif chart.birth_time_accuracy != "unknown":
            lines.append("Houses and angles are unavailable for this chart.")
    if chart.aspects:
        lines.append("Closest aspects (up to five, within 6°):")
        for a in sorted(chart.aspects, key=lambda a: a.orb)[:5]:
            motion = (
                "motion indeterminate"
                if a.applying is None
                else ("applying" if a.applying else "separating")
            )
            prefix = "Natal " if facts.transits is not None else ""
            other = "transiting " if facts.transits is not None else ""
            lines.append(
                f"{prefix}{a.body_a.title()} — {other}{a.body_b.title()}: "
                f"{a.name}, orb {a.orb:.2f}°; {motion}."
            )
    elif chart.birth_time_accuracy != "unknown":
        lines.append("No major aspects within the configured 6° orb.")
    if facts.transits is not None:
        lines.append("Transit houses/angles and time-to-exact are unavailable.")
    return "\n".join(lines)
