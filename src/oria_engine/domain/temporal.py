"""English/Gregorian temporal candidates. No model, persistence or tool authority.

Event precision is separate from the legacy transit sampling convention. All clocks
come from persisted ingress, never datetime.now(). Supplied anchors are local to the
caller; labels are not account selectors.
"""

import calendar
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from pydantic import Field

from oria_engine.astrology.contracts import WireModel
from oria_engine.domain.birth_time import birth_zone
from oria_engine.domain.policy import normalize
from oria_engine.domain.relative_time import (
    NUMBERS,
    OFFSET,
    TimeClarification,
    TimezoneRequired,
    local_instant,
    resolve_relative,
)
from oria_engine.knowledge.contracts import (
    CalendarDate,
    DateInterval,
    Instant,
    LocalDateTime,
    PartialDate,
    RecordRef,
    TemporalEvidence,
)

RESOLUTION_VERSION = "english-gregorian-2"
Role = Literal[
    "life_event", "birth_input", "anniversary", "profile_correction", "target", "context"
]
Issue = Literal["timezone", "anchor", "year", "leap_day", "clock", "date"]


class EventAnchor(WireModel):
    label: str = Field(min_length=1, max_length=160)
    day: date
    recurring: bool = False
    reference: RecordRef | None = None
    leap_day_observance: Literal["february_28", "march_1"] | None = None


class TemporalMention(WireModel):
    start: int
    end: int
    role: Role
    evidence: TemporalEvidence
    issue: Issue | None = None
    anchor_label: str | None = None


class TemporalAnalysis(WireModel):
    mentions: tuple[TemporalMention, ...] = Field(default=(), max_length=64)
    narrative: bool = False


MONTHS = {name.casefold(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.casefold(): i for i, name in enumerate(calendar.month_abbr) if name})
MONTHS["sept"] = 9
MONTH_PATTERN = "(?:" + "|".join(MONTHS) + ")"
COUNT = r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
ANCHOR_NAME = (
    r"(?:my (?:birthday|wedding(?: day| anniversary)?|anniversary)|"
    r"our wedding(?: day| anniversary)?|"
    r"the day I (?:was born|bought my house|got the cat|changed my job|founded my business)|"
    r"the day my parents got divorced|"
    r"(?:my|our) (?:[\w'-]+\s+){0,3}(?:birthday|anniversary))"
)
ANCHOR = re.compile(
    rf"(?:(?:{COUNT})\s+(?:days?|weeks?|months?|years?)\s+(?:before|after)\s+)?"
    rf"{ANCHOR_NAME}(?:\s+(?:in\s+\d{{4}}|(?:this|next|last) year))?",
    re.I,
)
DATE = re.compile(
    rf"\d{{4}}-\d{{2}}-\d{{2}}|"
    rf"{MONTH_PATTERN}\s+\d{{1,2}}(?!\d)(?:st|nd|rd|th)?"
    rf"(?:,?\s+(?:\d{{4}}|(?:last|this|next) year))?|"
    rf"\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH_PATTERN}(?:,?\s+(?:\d{{4}}|(?:last|this|next) year))?|"
    rf"this day (?:last|next) year|"
    rf"(?:exactly\s+)?(?:in\s+)?{COUNT}\s+(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)"
    rf"(?:\s+(?:ago|from now|later))?|"
    rf"day after tomorrow|day before yesterday|tomorrow|yesterday|today|tonight|now|"
    rf"(?:next|last|this)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|year)|"
    rf"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    rf"{MONTH_PATTERN}(?:\s+\d{{4}})?|\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{4}}",
    re.I,
)
# Match ambiguous numeric formats before standalone years.
NUMERIC = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{4}\b")
SUFFIX_CLOCK = re.compile(r"\s+(?:at\s+)(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
SUFFIX_PART = re.compile(r"\s+(?:at\s+)?(morning|afternoon|evening|noon|midnight)\b", re.I)
ZONE = re.compile(r"\b(?:[A-Za-z_+-]+/[A-Za-z_+/-]+|UTC)\b")
BAD_ZONE = re.compile(r"\b(?:GMT|EST|EDT|CST|CDT|PST|PDT|CET|CEST|BST|IST|JST|AEST|AEDT)\b", re.I)
BIRTH = re.compile(r"\b(?:born|birthday|birthplace|birth date|birth time|date of birth)\b", re.I)
EVENT = re.compile(
    r"\b(?:married|wedding|divorced|divorce|bought|purchased|adopted|got (?:the|a|my|our)|"
    r"changed (?:my |our )?job|started|founded|founding|graduated|moved|died|passed away|"
    r"born|birthday|anniversary|travelled|traveled|met|lost|retired)\b",
    re.I,
)
NARRATIVE = re.compile(
    r"\b(?:I|we|she|he|they)\s+(?:had|have|got|went|felt|feel|was|were|am|are)\b", re.I
)
HYPOTHETICAL = re.compile(r"\b(?:if|imagine|suppose|for example|hypothetically)\b", re.I)
READING = re.compile(
    r"\b(?:transits?|reading|forecast|horoscope|how(?:'s| is| will)|what.*(?:chart|stars))\b", re.I
)
CLAUSE = re.compile(
    r"[;\n!?]|\.(?!\d)|\band\s+(?=(?:I|we|my|our|her|his|their|can|what|how)\b)", re.I
)


def clauses(text: str) -> list[tuple[int, int]]:
    result = []
    start = 0
    for match in CLAUSE.finditer(text):
        result.append((start, match.start()))
        start = match.end()
    result.append((start, len(text)))
    return result


def role_for(clause: str) -> Role:
    clause = normalize(clause)
    if HYPOTHETICAL.search(clause) and not READING.search(clause):
        return "context"
    if (
        ANCHOR.search(clause)
        and READING.search(clause)
        and not re.search(r"\b(?:was born|we married)\b", clause, re.I)
    ):
        return "target"
    if BIRTH.search(clause):
        if re.search(r"\b(?:change|correct|edit)\s+my\s+(?:birth|date of birth)", clause, re.I):
            return "profile_correction"
        if ANCHOR.search(clause) and re.search(
            r"\b(?:before|after|next|anniversary)\b", clause, re.I
        ):
            return "target" if READING.search(clause) else "anniversary"
        return "birth_input"
    if ANCHOR.search(clause) and re.search(r"\b(?:before|after|anniversary)\b", clause, re.I):
        return "target" if READING.search(clause) else "anniversary"
    if EVENT.search(clause):
        return "life_event"
    return "target" if READING.search(clause) else "context"


def anchor_pattern(anchors: tuple[EventAnchor, ...]) -> re.Pattern[str]:
    names = "|".join(re.escape(a.label) for a in anchors)
    base = ANCHOR_NAME + ("|" + names if names else "")
    return re.compile(
        rf"(?:(?:{COUNT})\s+(?:days?|weeks?|months?|years?)\s+(?:before|after)\s+)?"
        rf"(?:{base})(?:\s+(?:in\s+\d{{4}}|(?:this|next|last) year))?",
        re.I,
    )


def shift_months(day: date, count: int) -> date:
    year, month = divmod(day.year * 12 + day.month - 1 + count, 12)
    month += 1
    return day.replace(
        year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1])
    )


def _year(text: str, local: date | None) -> int | None:
    match = re.search(r"\b\d{4}\b", text)
    if match:
        return int(match[0])
    match = re.search(r"\b(last|this|next) year\b", text, re.I)
    if match:
        if local is None:
            raise TimezoneRequired()
        return local.year + {"last": -1, "this": 0, "next": 1}[match[1].lower()]
    return None


def _clock(match: re.Match[str]) -> time:
    hour, minute, meridian = match.groups()
    h, m = int(hour), int(minute or 0)
    if meridian:
        if not 1 <= h <= 12:
            raise TimeClarification()
        h = h % 12 + (12 if meridian.lower() == "pm" else 0)
    elif minute is None:
        raise TimeClarification()
    return time(h, m)


def _resolve(
    expression: str, reference: datetime, zone: str | None, anchors: tuple[EventAnchor, ...]
) -> tuple[
    CalendarDate | Instant | LocalDateTime | PartialDate | None, Issue | None, EventAnchor | None
]:
    value = expression.casefold().strip()
    local = reference.astimezone(birth_zone(zone)).date() if zone else None
    clock_match = SUFFIX_CLOCK.search(value)
    part_match = SUFFIX_PART.search(value)
    clock_suffix = clock_match or part_match
    core = value[: clock_suffix.start()].strip() if clock_suffix else value
    approximate = bool(re.match(r"(?:around|about|roughly|approximately)\s+", core))
    core = re.sub(r"^(?:around|about|roughly|approximately)\s+", "", core)
    anchor_match = anchor_pattern(anchors).fullmatch(core)
    anchor = None
    day: date | None = None
    if anchor_match:
        name = re.sub(
            rf"^{COUNT}\s+(?:days?|weeks?|months?|years?)\s+(?:before|after)\s+", "", core
        )
        name = re.sub(r"\s+(?:in\s+\d{4}|(?:this|next|last) year)$", "", name)
        matches = [a for a in anchors if a.label.casefold() == name]
        if len(matches) != 1:
            return None, "anchor", None
        anchor = matches[0]
        day = anchor.day
        if anchor.recurring:
            year = _year(core, local)
            if year is None:
                return None, "year", anchor
            if day.month == 2 and day.day == 29 and not calendar.isleap(year):
                if anchor.leap_day_observance is None:
                    return None, "leap_day", anchor
                month, anniversary_day = (
                    (2, 28) if anchor.leap_day_observance == "february_28" else (3, 1)
                )
                day = date(year, month, anniversary_day)
            else:
                day = day.replace(year=year)
        offset = re.match(rf"({COUNT})\s+(days?|weeks?|months?|years?)\s+(before|after)", core)
        if offset:
            count = int(offset[1]) if offset[1].isdigit() else NUMBERS[offset[1]]
            count *= -1 if offset[3] == "before" else 1
            unit = offset[2].rstrip("s")
            day = (
                shift_months(day, count * (12 if unit == "year" else 1))
                if unit in {"month", "year"}
                else day + timedelta(days=count * (7 if unit == "week" else 1))
            )
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", core):
        day = date.fromisoformat(core)
    elif month_match := re.search(MONTH_PATTERN, core):
        month = MONTHS[month_match[0]]
        year = _year(core, local)
        without_year = re.sub(r"\b\d{4}\b|(?:last|this|next) year", "", core)
        number = re.search(r"\d{1,2}", without_year)
        if not number:
            return PartialDate(year=year, month=month, approximate=approximate), None, None
        if year is None:
            return PartialDate(month=month, day=int(number[0]), approximate=approximate), None, None
        day = date(year, month, int(number[0]))
    elif re.fullmatch(r"\d{4}", core):
        return PartialDate(year=int(core), approximate=approximate), None, None
    elif core in {"this day last year", "this day next year"}:
        if local is None:
            raise TimezoneRequired()
        day = shift_months(local, -12 if "last" in core else 12)
    elif core == "now":
        return Instant(value=reference.astimezone(UTC), approximate=approximate), None, None
    else:
        offset = OFFSET.fullmatch(re.sub(r"^exactly\s+", "", core))
        if offset and (offset[1] or offset[4]):
            count = int(offset[2]) if offset[2].isdigit() else NUMBERS[offset[2]]
            if count > 10000:
                raise TimeClarification()
            count *= -1 if offset[4] == "ago" else 1
            unit = offset[3].rstrip("s")
            if unit in {"second", "minute", "hour"}:
                if clock_match:
                    raise TimeClarification()
                return (
                    Instant(
                        value=reference.astimezone(UTC) + timedelta(**{unit + "s": count}),
                        approximate=approximate,
                    ),
                    None,
                    None,
                )
            if local is None:
                raise TimezoneRequired()
            day = (
                shift_months(local, count * (12 if unit == "year" else 1))
                if unit in {"month", "year"}
                else local + timedelta(days=count * (7 if unit == "week" else 1))
            )
        else:
            resolved = resolve_relative(core, reference, zone)
            if resolved is None:
                raise TimeClarification()
            assert zone is not None
            day = resolved.astimezone(birth_zone(zone)).date()
    assert day is not None
    if clock_match or (part_match and part_match[1] in {"noon", "midnight"}):
        try:
            clock = (
                _clock(clock_match)
                if clock_match
                else time(12 if part_match and part_match[1] == "noon" else 0)
            )
        except ValueError:
            return None, "clock", anchor
        if zone is None:
            return (
                LocalDateTime(value=datetime.combine(day, clock), approximate=approximate),
                None,
                anchor,
            )
        try:
            return (
                Instant(value=local_instant(day, clock, zone), approximate=approximate),
                None,
                anchor,
            )
        except TimeClarification:
            return None, "clock", anchor
    return CalendarDate(value=day, approximate=approximate), None, anchor


def analyze_temporal(
    text: str,
    *,
    received_at: datetime,
    current_timezone: str | None = None,
    anchors: tuple[EventAnchor, ...] = (),
    timezone_source: Literal["explicit_event", "current_preference"] = "current_preference",
) -> TemporalAnalysis:
    """Extract all bounded temporal mentions with provenance and independent roles.

    Dates in a narrative never authorize calculations. Unknown/ambiguous constructs
    remain candidates requiring clarification rather than being guessed by a model.
    """
    if received_at.utcoffset() is None:
        raise ValueError("Message time must be aware")
    mentions: list[TemporalMention] = []
    normalized = normalize(text)
    narrative = bool(
        EVENT.search(normalized)
        or BIRTH.search(normalized)
        or NARRATIVE.search(normalized)
        or HYPOTHETICAL.search(normalized)
    )
    available = list(anchors)
    for begin, end in clauses(text):
        clause = text[begin:end]
        first_mention = len(mentions)
        role = role_for(clause)
        zone_matches = list(ZONE.finditer(clause))
        zone = zone_matches[0][0] if len(zone_matches) == 1 else current_timezone
        zone_issue = len(zone_matches) > 1 or bool(BAD_ZONE.search(clause))
        if zone:
            try:
                birth_zone(zone)
            except (KeyError, ValueError):
                zone_issue = True
                zone = None
        candidates = sorted(
            [
                *anchor_pattern(tuple(available)).finditer(clause),
                *NUMERIC.finditer(clause),
                *DATE.finditer(clause),
            ],
            key=lambda m: (m.start(), -m.end()),
        )
        consumed = -1
        for match in candidates:
            if match.start() < consumed or len(mentions) >= 64:
                continue
            left, right = match.span()
            if (
                match[0].casefold() in MONTHS
                and clause.strip().casefold() != match[0].casefold()
                and not READING.search(clause)
                and not re.search(
                    r"\b(?:in|during|around|about|for|of|by|until)\s+$", clause[:left], re.I
                )
            ):
                continue
            if ANCHOR.fullmatch(match[0]) and re.match(r"\s+(?:is|was|on)\b", clause[right:], re.I):
                continue
            # Do not match years/counts embedded in identifiers or numeric formats.
            if (left and (clause[left - 1].isalnum() or clause[left - 1] in "-/+.")) or (
                right < len(clause) and clause[right].isalnum()
            ):
                continue
            clock_match = SUFFIX_CLOCK.match(clause, right)
            part_match = SUFFIX_PART.match(clause, right)
            if clock_match or part_match:
                suffix = clock_match or part_match
                assert suffix is not None
                right = suffix.end()
            dangling_clock = re.match(r"\s+at\s*$", clause[right:], re.I)
            if dangling_clock:
                right = len(clause)
            prefix = re.search(r"\b(?:around|about|roughly|approximately)\s+$", clause[:left], re.I)
            if prefix:
                left = prefix.start()
            expression = clause[left:right]
            consumed = right
            result = None
            anchor = None
            issue: Issue | None = "timezone" if zone_issue else None
            if issue is None:
                try:
                    result, issue, anchor = _resolve(
                        expression, received_at, zone, tuple(available)
                    )
                except TimezoneRequired:
                    issue = "timezone"
                except (TimeClarification, ValueError, OverflowError):
                    issue = "date"
            if dangling_clock:
                issue = "clock"
            if role == "target" and expression.casefold() in {"today", "now"}:
                # Published transit v1 samples ingress for bare today/now.
                result, issue = Instant(value=received_at.astimezone(UTC)), None
            elif role == "target" and isinstance(result, LocalDateTime):
                issue = "timezone"
            name = re.search(ANCHOR_NAME, expression, re.I)
            evidence = TemporalEvidence(
                expression=expression,
                reference_time_utc=received_at.astimezone(UTC),
                timezone=zone,
                timezone_source=("explicit_event" if zone_matches else timezone_source)
                if zone
                else "unknown",
                anchor=anchor.reference if anchor else None,
                resolution_version=RESOLUTION_VERSION,
                value=result,
            )
            mentions.append(
                TemporalMention(
                    start=begin + left,
                    end=begin + right,
                    role="anniversary" if role == "context" and (anchor or name) else role,
                    evidence=evidence,
                    issue=issue,
                    anchor_label=anchor.label if anchor else name[0].casefold() if name else None,
                )
            )
            # Same-message anchors are provisional, never canonical saved events.
            if isinstance(result, CalendarDate) and role in {"life_event", "birth_input"}:
                label = None
                if re.search(r"\b(?:we married|our wedding|my wedding)\b", clause, re.I):
                    label = "our wedding day"
                elif re.search(r"\bI was born\b", clause, re.I):
                    label = "the day I was born"
                if label:
                    available.append(EventAnchor(label=label, day=result.value))
        # An unattached alternative clock is ambiguous. Independent event/date
        # pairs with their own clocks remain separate supported mentions.
        if any(
            not any(
                m.start <= begin + clock.start() and begin + clock.end() <= m.end
                for m in mentions[first_mention:]
            )
            for clock in SUFFIX_CLOCK.finditer(clause)
        ):
            mentions[first_mention:] = [
                m.model_copy(update={"issue": "date"}) for m in mentions[first_mention:]
            ]
    # Conversational date ranges preserve both endpoints; no interval tool is implied.
    if len(mentions) == 2 and re.search(r"\b(?:between|from)\b", text, re.I):
        first, second = mentions
        a, b = first.evidence.value, second.evidence.value
        if (
            isinstance(a, CalendarDate)
            and isinstance(b, CalendarDate)
            and first.role == second.role
        ):
            try:
                interval = DateInterval(start=a, end=b)
                mentions = [
                    first.model_copy(
                        update={
                            "end": second.end,
                            "evidence": first.evidence.model_copy(
                                update={
                                    "expression": text[first.start : second.end],
                                    "value": interval,
                                }
                            ),
                        }
                    )
                ]
            except ValueError:
                mentions = [m.model_copy(update={"issue": "date"}) for m in mentions]
    return TemporalAnalysis(mentions=tuple(mentions), narrative=narrative)


def clarification(issue: Issue) -> str:
    return {
        "timezone": (
            "Which timezone should I use for that date or local time? "
            "For example, Europe/Berlin or UTC. "
            "Use /timezone Europe/Berlin to also save that preference."
        ),
        "anchor": "What date is that event? You can give it naturally, for example May 1st, 2020.",
        "year": (
            "Which year or birthday occurrence do you mean: this year, next year, or another year?"
        ),
        "leap_day": (
            "For that non-leap year, do you observe the February 29 anniversary "
            "on February 28 or March 1?"
        ),
        "clock": (
            "What local clock time should I use? If a clock change skips or repeats it, "
            "please choose another time."
        ),
        "date": (
            "Which date or time do you mean? You can use May 1st, 2020, "
            "tomorrow at 15:30, or YYYY-MM-DD."
        ),
    }[issue]
