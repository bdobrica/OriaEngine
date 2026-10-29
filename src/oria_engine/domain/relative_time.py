"""Bounded English time grammar, anchored to persisted ingress time, without an LLM."""

import calendar
import re
from datetime import UTC, date, datetime, time, timedelta

from oria_engine.domain.birth_time import birth_zone, utc_candidates

NUMBERS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
OFFSET = re.compile(
    r"\b(?:(in)\s+)?(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve)\s+(seconds?|minutes?|hours?|days?|weeks?|months?|years?)"
    r"(?:\s+(ago|from now|later))?\b",
    re.I,
)
DAY = re.compile(r"\b(day after tomorrow|day before yesterday|tomorrow|yesterday|today)\b", re.I)
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WEEKDAY = re.compile(r"\b(?:(next|last|this)\s+)?(" + "|".join(WEEKDAYS) + r")\b", re.I)
PERIOD = re.compile(r"\b(next|last)\s+(week|month|year)\b", re.I)
CLOCK = re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
PART = re.compile(
    r"\b(?:(this|tomorrow|yesterday)\s+)?(morning|afternoon|evening|tonight|noon|midnight)\b", re.I
)
HINT = re.compile(
    r"\b(tomorrow|yesterday|tonight|next|last|ago|morning|afternoon|evening|noon|midnight|"
    r"seconds?|minutes?|hours?|days?|weeks?|months?|years?|later|soon|night)\b|\bat\s+\d",
    re.I,
)


class TimeClarification(ValueError):
    """Unsupported, ambiguous or out-of-range time; no user text in exceptions."""


class TimezoneRequired(TimeClarification):
    pass


def local_instant(day: date, clock: time, zone: str) -> datetime:
    candidates = utc_candidates(day, clock, zone)
    if len(candidates) != 1:
        raise TimeClarification("Clock change requires a different unambiguous time")
    return candidates[0]


def resolve_relative(text: str, received_at: datetime, zone: str | None) -> datetime | None:
    """Return one instant or clarify; periods mean a labelled single snapshot, not a range.

    Hours/minutes/seconds are elapsed UTC durations. Calendar days/weeks/months/years
    preserve local wall time. Named dates use local noon unless a clock is supplied.
    """
    value = text.casefold()
    offsets, days, weekdays, periods, clocks, parts = (
        list(pattern.finditer(value)) for pattern in (OFFSET, DAY, WEEKDAY, PERIOD, CLOCK, PART)
    )
    # A part containing 'tomorrow morning' overlaps the day intentionally.
    anchors = len(offsets) + len(days) + len(weekdays) + len(periods)
    if not (anchors or clocks or parts):
        if HINT.search(value):
            raise TimeClarification()
        return None
    if anchors > 1 or len(clocks) + len(parts) > 1:
        raise TimeClarification()
    remainder = value
    for pattern in (OFFSET, DAY, WEEKDAY, PERIOD, CLOCK, PART):
        remainder = pattern.sub(" ", remainder)
    if re.search(
        r"\d|\b(today|now|current|next|last|this|or|between|until|through|weekend|"
        r"later|soon|night|utc|gmt|est|edt|cst|cdt|pst|pdt|cet|cest|bst|ist|jst|aest|aedt)\b",
        remainder,
    ):
        raise TimeClarification()
    if offsets:
        match = offsets[0]
        if not (match[1] or match[4]):
            raise TimeClarification()
        count = int(match[2]) if match[2].isdigit() else NUMBERS[match[2]]
        if count > 10000:
            raise TimeClarification()
        if match[4] == "ago":
            if match[1]:
                raise TimeClarification()
            count = -count
        unit = match[3].rstrip("s")
        if unit in {"second", "minute", "hour"}:
            if clocks or parts:
                raise TimeClarification()
            return received_at.astimezone(UTC) + timedelta(**{unit + "s": count})
    if zone is None:
        raise TimezoneRequired()
    local = received_at.astimezone(birth_zone(zone))
    day, clock = local.date(), time(12)
    if offsets or periods:
        if periods:
            count = 1 if periods[0][1] == "next" else -1
            unit = periods[0][2]
        if unit in {"day", "week"}:
            day += timedelta(days=count * (7 if unit == "week" else 1))
        else:
            months = local.year * 12 + local.month - 1 + count * (12 if unit == "year" else 1)
            year, month = divmod(months, 12)
            month += 1
            day = day.replace(
                year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1])
            )
        clock = local.time().replace(tzinfo=None)
    elif days:
        day += timedelta(
            days={
                "today": 0,
                "tomorrow": 1,
                "yesterday": -1,
                "day after tomorrow": 2,
                "day before yesterday": -2,
            }[days[0][0]]
        )
    elif weekdays:
        match = weekdays[0]
        distance = (WEEKDAYS.index(match[2]) - local.weekday()) % 7
        if match[1] == "last":
            distance = distance - 7 if distance else -7
        elif match[1] != "this" and distance == 0:
            distance = 7
        day += timedelta(days=distance)
    if clocks:
        hour, minute, meridian = clocks[0].groups()
        h, m = int(hour), int(minute or 0)
        if meridian:
            if not 1 <= h <= 12:
                raise TimeClarification()
            h = h % 12 + (12 if meridian == "pm" else 0)
        elif minute is None:
            raise TimeClarification()
        clock = time(h, m)
    elif parts:
        modifier, part = parts[0].groups()
        if not days and modifier in {"tomorrow", "yesterday"}:
            day += timedelta(days=1 if modifier == "tomorrow" else -1)
        clock = time(
            {
                "morning": 9,
                "afternoon": 15,
                "evening": 18,
                "tonight": 21,
                "noon": 12,
                "midnight": 0,
            }[part]
        )
    return local_instant(day, clock, zone)
