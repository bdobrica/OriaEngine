"""Additive transit v1 contract. Natal references contain no raw birth inputs."""

from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import model_validator

from oria_engine.astrology.contracts import (
    Accuracy,
    Angle,
    Aspect,
    Body,
    CalculationMetadata,
    NatalResult,
    Planet,
    WireModel,
)


def validate_target(instant: datetime) -> None:
    if instant.utcoffset() != timedelta(0) or not 1800 <= instant.year <= 2399:
        raise ValueError("Target requires explicit UTC in years 1800 through 2399")


class NatalPosition(WireModel):
    body: Body
    longitude: Angle


class TransitRequest(WireModel):
    contract_version: Literal[1] = 1
    target_timestamp_utc: datetime
    birth_time_accuracy: Accuracy
    natal_positions: tuple[NatalPosition, ...]

    @model_validator(mode="after")
    def valid_request(self) -> Self:
        validate_target(self.target_timestamp_utc)
        if self.birth_time_accuracy == "unknown":
            if self.natal_positions:
                raise ValueError("Unknown birth time cannot supply natal positions")
        elif len(self.natal_positions) != 10 or len({p.body for p in self.natal_positions}) != 10:
            raise ValueError("Expected ten distinct natal bodies")
        return self

    @classmethod
    def from_natal(cls, natal: NatalResult, target: datetime) -> Self:
        return cls(
            target_timestamp_utc=target,
            birth_time_accuracy=natal.birth_time_accuracy,
            natal_positions=tuple(
                NatalPosition(body=p.body, longitude=p.longitude) for p in natal.planets
            ),
        )


class TransitMetadata(WireModel):
    engine_version: Literal["oria-transits-1"] = "oria-transits-1"
    astronomy: CalculationMetadata = CalculationMetadata()
    aspect_reference: Literal["body_a_fixed_natal_body_b_transiting"] = (
        "body_a_fixed_natal_body_b_transiting"
    )
    time_to_exact_method: Literal["unavailable"] = "unavailable"


class TransitAvailability(WireModel):
    positions: Literal[True] = True
    natal_aspects: bool
    houses: Literal[False] = False
    angles: Literal[False] = False
    time_to_exact: Literal[False] = False
    reasons: tuple[Literal["unknown_birth_time", "approximate_birth_time"], ...] = ()


class TransitResult(WireModel):
    contract_version: Literal[1] = 1
    target_timestamp_utc: datetime
    birth_time_accuracy: Accuracy
    planets: tuple[Planet, ...]
    aspects: tuple[Aspect, ...]
    availability: TransitAvailability
    metadata: TransitMetadata

    @model_validator(mode="after")
    def consistent_result(self) -> Self:
        validate_target(self.target_timestamp_utc)
        if len(self.planets) != 10 or len({p.body for p in self.planets}) != 10:
            raise ValueError("Expected ten distinct transiting bodies")
        if any(p.house is not None for p in self.planets):
            raise ValueError("Transit houses are not supplied")
        expected = {
            "exact": (),
            "approximate": ("approximate_birth_time",),
            "unknown": ("unknown_birth_time",),
        }[self.birth_time_accuracy]
        if self.availability.reasons != expected:
            raise ValueError("Inconsistent birth-time uncertainty")
        if self.availability.natal_aspects != (self.birth_time_accuracy != "unknown"):
            raise ValueError("Inconsistent natal aspect availability")
        if not self.availability.natal_aspects and self.aspects:
            raise ValueError("Unknown birth time cannot supply natal aspects")
        pairs = [(a.body_a, a.body_b) for a in self.aspects]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Duplicate natal-to-transit pair")
        return self
