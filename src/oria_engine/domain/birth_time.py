"""Historical conversion with explicit round-trip validation, never guessed offsets."""

from datetime import UTC, date, datetime, time
from functools import lru_cache
from importlib.resources import files
from io import BytesIO
from zipfile import ZipFile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@lru_cache(maxsize=512)
def birth_zone(name: str) -> ZoneInfo:
    """Use the bundled IANA snapshot, independent of the host timezone database."""
    try:
        with (
            files("oria_engine").joinpath("data/timezones.zip").open("rb") as source,
            ZipFile(source) as archive,
        ):
            data = archive.read(name)
        return ZoneInfo.from_file(BytesIO(data), key=name)
    except (KeyError, ValueError):
        raise ZoneInfoNotFoundError("Unsupported birth timezone") from None


def utc_candidates(day: date, local_time: time, timezone: str) -> tuple[datetime, ...]:
    """Zero instants means a gap; two means a repeated wall time, ordered by UTC."""
    if local_time.tzinfo is not None:
        raise ValueError("Expected offset-free local time")
    wall = datetime.combine(day, local_time).replace(fold=0)
    zone = birth_zone(timezone)
    instants = set()
    try:
        for fold in (0, 1):
            instant = wall.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            if instant.astimezone(zone).replace(tzinfo=None, fold=0) == wall:
                instants.add(instant)
    except (OverflowError, ValueError):
        raise ValueError("Birth time is outside the supported conversion range") from None
    return tuple(sorted(instants))


def resolve_utc(
    day: date, local_time: time | None, timezone: str, occurrence: int | None = None
) -> datetime | None:
    """Unknown stays unknown; a repeated time requires an explicit occurrence (0/1)."""
    if local_time is None:
        if occurrence is not None:
            raise ValueError("Unknown time cannot select an occurrence")
        return None
    candidates = utc_candidates(day, local_time, timezone)
    if not candidates:
        raise ValueError("Local time does not exist")
    if len(candidates) == 2:
        if occurrence not in (0, 1):
            raise ValueError("Local time requires clarification")
        return candidates[occurrence]
    if occurrence is not None:
        raise ValueError("Unambiguous time cannot select an occurrence")
    return candidates[0]
