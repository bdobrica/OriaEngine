"""Strict encrypted draft schema and deterministic input parsing."""

import re
from datetime import date, time
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from oria_engine.domain.birth_profile import BirthPlace, BirthProfilePayload, PrivateModel
from oria_engine.domain.birth_time import resolve_utc
from oria_engine.domain.policy import ONBOARDING_FIELDS


class OnboardingDraft(PrivateModel):
    schema_version: Literal[1] = 1
    consent_id: UUID
    token: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    birth_date: date | None = None
    birth_local_time: time | None = None
    birth_time_accuracy: Literal["exact", "approximate", "unknown"] | None = None
    birth_place: BirthPlace | None = None
    birth_time_occurrence: Literal[0, 1] | None = None
    candidates: tuple[BirthPlace, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.birth_time_accuracy in {None, "unknown"}:
            if self.birth_local_time is not None:
                raise ValueError("Unexpected birth time")
        elif self.birth_local_time is None or self.birth_local_time.tzinfo is not None:
            raise ValueError("Known time requires an offset-free local time")
        if self.birth_place is not None and self.candidates:
            raise ValueError("Selected place cannot have pending candidates")
        if self.birth_time_occurrence is not None:
            if self.birth_date is None or self.birth_place is None:
                raise ValueError("Time clarification requires date and place")
            resolve_utc(
                self.birth_date,
                self.birth_local_time,
                self.birth_place.timezone,
                self.birth_time_occurrence,
            )
        return self

    def profile(self) -> BirthProfilePayload:
        return BirthProfilePayload.model_validate(
            self.model_dump(include=set(ONBOARDING_FIELDS)) | {"schema_version": 2}
        )


def parse_birth_date(text: str) -> date:
    """Accept ISO YYYY-MM-DD or explicit DD Mon YYYY (English month abbreviation)."""
    text = text.strip()
    try:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
            result = date.fromisoformat(text)
        else:
            match = re.fullmatch(r"([0-9]{1,2}) ([A-Za-z]{3}) ([0-9]{4})", text)
            if match is None:
                raise ValueError()
            months = [
                "jan",
                "feb",
                "mar",
                "apr",
                "may",
                "jun",
                "jul",
                "aug",
                "sep",
                "oct",
                "nov",
                "dec",
            ]
            result = date(int(match[3]), months.index(match[2].lower()) + 1, int(match[1]))
        if result > date.today():
            raise ValueError()
        return result
    except ValueError:
        raise ValueError("Use YYYY-MM-DD or DD Mon YYYY; date must not be in the future") from None


def parse_birth_time(text: str) -> tuple[time | None, Literal["exact", "approximate", "unknown"]]:
    text = text.strip().lower()
    if text == "unknown":
        return None, "unknown"
    match = re.fullmatch(r"(?:(exact|approximate) )?([0-9]{2}):([0-9]{2})", text)
    if match is not None:
        try:
            value = time(int(match[2]), int(match[3]))
            return value, "approximate" if match[1] == "approximate" else "exact"
        except ValueError:
            pass
    raise ValueError("Use HH:MM, approximate HH:MM, or unknown")
