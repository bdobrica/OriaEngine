"""Versioned private calculation inputs; never log serialized models or validation inputs."""

from datetime import date, datetime, time
from typing import Literal, Self
from zoneinfo import ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from oria_engine.domain.birth_time import birth_zone, resolve_utc


class PrivateModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, revalidate_instances="always"
    )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(<redacted>)"

    def __str__(self) -> str:
        return self.__repr__()


class BirthPlace(PrivateModel):
    display_name: str = Field(min_length=1, max_length=256, repr=False)
    city: str = Field(min_length=1, max_length=128, repr=False)
    region: str | None = Field(default=None, min_length=1, max_length=128, repr=False)
    country_code: str = Field(pattern=r"^[A-Z]{2}$", repr=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False, repr=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False, repr=False)
    timezone: str = Field(min_length=1, max_length=128, repr=False)

    @field_validator("display_name", "city", "region")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Place name must not be blank")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            birth_zone(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone") from None
        return value


class BirthProfilePayload(PrivateModel):
    schema_version: Literal[1, 2] = 1
    birth_date: date = Field(repr=False)
    birth_local_time: time | None = Field(default=None, repr=False)
    birth_time_accuracy: Literal["exact", "approximate", "unknown"] = Field(repr=False)
    birth_place: BirthPlace = Field(repr=False)
    birth_time_occurrence: Literal[0, 1] | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def consistent_time(self) -> Self:
        if self.schema_version == 1 and self.birth_time_occurrence is not None:
            raise ValueError("Time clarification requires profile schema version 2")
        if (self.birth_time_accuracy == "unknown") != (self.birth_local_time is None):
            raise ValueError("Known time requires a local time; unknown time requires no time")
        if self.birth_local_time is not None and self.birth_local_time.tzinfo is not None:
            raise ValueError("Birth time must be local without a UTC offset")
        if self.schema_version == 2:
            self.utc_instant()
        return self

    def utc_instant(self) -> datetime | None:
        """Derived input, never an authority over original local values/accuracy."""
        return resolve_utc(
            self.birth_date,
            self.birth_local_time,
            self.birth_place.timezone,
            self.birth_time_occurrence,
        )
