"""Astrology MCP v1 wire models. No identity fields; never log serialized values."""

from datetime import date, datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Body = Literal[
    "sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune", "pluto"
]
Angle = Annotated[float, Field(ge=0, lt=360, allow_inf_nan=False)]
Number = Annotated[float, Field(allow_inf_nan=False)]
Accuracy = Literal["exact", "approximate", "unknown"]


class WireModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, revalidate_instances="always"
    )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(<redacted>)"

    def __str__(self) -> str:
        return self.__repr__()


class NatalRequest(WireModel):
    contract_version: Literal[1] = 1
    timestamp_utc: datetime | None = None
    local_birth_date: date | None = None
    birth_time_accuracy: Accuracy
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    house_system: Literal["P"] = "P"

    @model_validator(mode="after")
    def valid_time(self) -> Self:
        if self.birth_time_accuracy == "unknown":
            if self.timestamp_utc is not None or self.local_birth_date is None:
                raise ValueError("Unknown time requires only a local date")
            year = self.local_birth_date.year
        else:
            if self.timestamp_utc is None or self.local_birth_date is not None:
                raise ValueError("Known time requires only a UTC instant")
            if self.timestamp_utc.utcoffset() != timedelta(0):
                raise ValueError("Instant must have an explicit UTC offset of zero")
            year = self.timestamp_utc.year
        if not 1800 <= year <= 2399:
            raise ValueError("Supported years are 1800 through 2399")
        return self


class Planet(WireModel):
    body: Body
    longitude: Angle
    sign: Literal[
        "Aries",
        "Taurus",
        "Gemini",
        "Cancer",
        "Leo",
        "Virgo",
        "Libra",
        "Scorpio",
        "Sagittarius",
        "Capricorn",
        "Aquarius",
        "Pisces",
    ]
    degree_in_sign: float = Field(ge=0, lt=30, allow_inf_nan=False)
    longitude_velocity_deg_day: Number
    retrograde: bool
    house: int | None = Field(default=None, ge=1, le=12)


class Angles(WireModel):
    ascendant: Angle
    midheaven: Angle


class Aspect(WireModel):
    body_a: Body
    body_b: Body
    name: Literal["conjunction", "sextile", "square", "trine", "opposition"]
    target_angle: Literal[0, 60, 90, 120, 180]
    angular_separation: float = Field(ge=0, le=180, allow_inf_nan=False)
    orb: float = Field(ge=0, le=6, allow_inf_nan=False)
    relative_velocity_deg_day: Number
    applying: bool | None
    time_to_exact_hours: None = None


class CalculationMetadata(WireModel):
    engine_version: Literal["oria-natal-1"] = "oria-natal-1"
    binding_version: Literal["2.10.3.2"] = "2.10.3.2"
    swiss_ephemeris_version: Literal["2.10.03"] = "2.10.03"
    ephemeris: Literal["moshier"] = "moshier"
    ephemeris_data_version: Literal["bundled-with-swisseph-2.10.03"] = (
        "bundled-with-swisseph-2.10.03"
    )
    zodiac: Literal["tropical"] = "tropical"
    reference_frame: Literal["apparent-geocentric-ecliptic-of-date"] = (
        "apparent-geocentric-ecliptic-of-date"
    )
    house_system: Literal["P"] = "P"
    aspect_orb_degrees: Literal[6] = 6


class Availability(WireModel):
    positions: bool
    houses: bool
    angles: bool
    aspects: bool
    time_to_exact: Literal[False] = False
    reasons: tuple[
        Literal["unknown_birth_time", "approximate_birth_time", "houses_unsupported"], ...
    ] = ()


class NatalResult(WireModel):
    contract_version: Literal[1] = 1
    birth_time_accuracy: Accuracy
    planets: tuple[Planet, ...]
    angles: Angles | None
    house_cusps: tuple[Angle, ...]
    aspects: tuple[Aspect, ...]
    availability: Availability
    metadata: CalculationMetadata

    @model_validator(mode="after")
    def consistent_availability(self) -> Self:
        if self.availability.positions != bool(self.planets):
            raise ValueError("Inconsistent position availability")
        if self.planets and (len(self.planets) != 10 or len({p.body for p in self.planets}) != 10):
            raise ValueError("Expected ten distinct bodies")
        if self.availability.angles != (self.angles is not None):
            raise ValueError("Inconsistent angle availability")
        if self.availability.houses != (len(self.house_cusps) == 12):
            raise ValueError("Inconsistent house availability")
        if not self.availability.houses and (
            self.house_cusps or any(p.house is not None for p in self.planets)
        ):
            raise ValueError("Unavailable houses must be absent")
        if self.availability.houses and any(p.house is None for p in self.planets):
            raise ValueError("Available houses require planet placements")
        if not self.availability.aspects and self.aspects:
            raise ValueError("Unavailable aspects must be absent")
        if (
            self.birth_time_accuracy == "approximate"
            and "approximate_birth_time" not in self.availability.reasons
        ):
            raise ValueError("Approximate time requires an uncertainty reason")
        if self.birth_time_accuracy == "unknown" and (
            self.planets
            or self.angles
            or self.house_cusps
            or self.aspects
            or self.availability.aspects
        ):
            raise ValueError("Unknown time cannot supply time-dependent facts")
        return self
