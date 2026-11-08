"""Additive linked-chart v1 contracts. Sampling never asserts a known birth instant."""

from datetime import date, datetime, timedelta
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from oria_engine.astrology.contracts import (
    Accuracy,
    Angle,
    Angles,
    Body,
    CalculationMetadata,
    Planet,
    WireModel,
)


class ChartInput(WireModel):
    accuracy: Accuracy
    timestamp_utc: datetime | None = None
    calendar_date: date | None = None
    date_approximate: bool = False
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_input(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Coordinates must be supplied together")
        if self.accuracy == "unknown":
            if self.timestamp_utc is not None or self.calendar_date is None:
                raise ValueError("Unknown time requires only a calendar date")
            year = self.calendar_date.year
        else:
            if self.date_approximate:
                raise ValueError("Date uncertainty belongs to date sampling")
            if self.timestamp_utc is None or self.calendar_date is not None:
                raise ValueError("Known time requires only a UTC instant")
            if self.timestamp_utc.utcoffset() != timedelta(0):
                raise ValueError("Expected an explicit UTC instant")
            year = self.timestamp_utc.year
        if not 1800 <= year <= 2399:
            raise ValueError("Supported calculation years are 1800 through 2399")
        return self


class LinkedMetadata(WireModel):
    engine_version: Literal["oria-linked-1"] = "oria-linked-1"
    astronomy: CalculationMetadata = Field(default_factory=CalculationMetadata)
    date_sampling: Literal["calendar-date-at-12-utc-1"] = "calendar-date-at-12-utc-1"
    comparison: Literal["static-longitude-major-6deg-1"] = "static-longitude-major-6deg-1"


class ChartFacts(WireModel):
    precision: Literal["exact", "approximate", "date_sample"]
    planets: tuple[Planet, ...] = Field(min_length=10, max_length=10)
    house_cusps: tuple[Angle, ...] = ()
    angles: Angles | None = None
    reasons: tuple[
        Literal[
            "date_only_sample",
            "approximate_date",
            "approximate_time",
            "place_unknown",
            "houses_unsupported",
        ],
        ...,
    ] = ()

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if len({p.body for p in self.planets}) != 10:
            raise ValueError("Expected distinct bodies")
        signs = (
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
        )
        for p in self.planets:
            if (
                p.sign != signs[int(p.longitude // 30)]
                or abs(p.degree_in_sign - p.longitude % 30) > 1e-8
            ):
                raise ValueError("Inconsistent planetary sign")
        if len(self.house_cusps) not in {0, 12}:
            raise ValueError("Expected all twelve cusps or none")
        houses = bool(self.house_cusps)
        if houses:
            spans = tuple(
                (self.house_cusps[(i + 1) % 12] - cusp) % 360
                for i, cusp in enumerate(self.house_cusps)
            )
            if any(span <= 0 for span in spans) or abs(sum(spans) - 360) > 1e-8:
                raise ValueError("Cusps must describe one complete circle")
            for p in self.planets:
                if p.house is not None:
                    start = self.house_cusps[p.house - 1]
                    if (p.longitude - start) % 360 >= spans[p.house - 1]:
                        raise ValueError("Inconsistent planetary house")
        if houses != (self.angles is not None) or any(
            (p.house is not None) != houses for p in self.planets
        ):
            raise ValueError("Inconsistent house availability")
        if self.precision == "date_sample" and (houses or "date_only_sample" not in self.reasons):
            raise ValueError("A sampled date cannot supply houses or angles")
        if self.precision == "approximate" and "approximate_time" not in self.reasons:
            raise ValueError("Approximate time needs its reason")
        if self.precision != "date_sample" and "date_only_sample" in self.reasons:
            raise ValueError("Unexpected sampling reason")
        return self


class ChartRequest(WireModel):
    contract_version: Literal[1] = 1
    calculation_id: UUID  # Ephemeral correlation token, never an account/record ID.
    chart: ChartInput


class ChartResult(WireModel):
    contract_version: Literal[1] = 1
    calculation_id: UUID
    chart: ChartFacts
    metadata: LinkedMetadata = Field(default_factory=LinkedMetadata)


class CrossAspect(WireModel):
    body_a: Body
    body_b: Body
    name: Literal["conjunction", "sextile", "square", "trine", "opposition"]
    target_angle: Literal[0, 60, 90, 120, 180]
    angular_separation: float = Field(ge=0, le=180, allow_inf_nan=False)
    orb: float = Field(ge=0, le=6, allow_inf_nan=False)


class Overlay(WireModel):
    direction: Literal["a_in_b", "b_in_a"]
    body: Body
    house: int = Field(ge=1, le=12)
    # A sampled body can move across a cusp even when the receiving chart is exact.
    precision: Literal["exact", "approximate", "date_sample"]


class SynastryRequest(WireModel):
    contract_version: Literal[1] = 1
    calculation_id: UUID
    chart_a: ChartInput
    chart_b: ChartInput


class SynastryResult(WireModel):
    contract_version: Literal[1] = 1
    calculation_id: UUID
    chart_a: ChartFacts
    chart_b: ChartFacts
    aspects: tuple[CrossAspect, ...] = Field(max_length=100)
    overlays: tuple[Overlay, ...] = Field(max_length=20)
    metadata: LinkedMetadata = Field(default_factory=LinkedMetadata)

    @model_validator(mode="after")
    def available_overlays(self) -> Self:
        aspects: dict[tuple[str, str], CrossAspect] = {}
        for supplied in self.aspects:
            key = (supplied.body_a, supplied.body_b)
            if key in aspects:
                raise ValueError("Duplicate cross aspect")
            aspects[key] = supplied
        targets = {"conjunction": 0, "sextile": 60, "square": 90, "trine": 120, "opposition": 180}
        expected = set()
        for a in self.chart_a.planets:
            for b in self.chart_b.planets:
                separation = abs((b.longitude - a.longitude + 180) % 360 - 180)
                for name, target in targets.items():
                    orb = abs(separation - target)
                    if orb <= 6:
                        key = (a.body, b.body)
                        expected.add(key)
                        aspect = aspects.get(key)
                        if (
                            aspect is None
                            or aspect.name != name
                            or aspect.target_angle != target
                            or abs(aspect.orb - orb) > 1e-8
                            or abs(aspect.angular_separation - separation) > 1e-8
                        ):
                            raise ValueError("Inconsistent cross aspect geometry")
        if set(aspects) != expected:
            raise ValueError("Unexpected cross aspects")
        seen = set()
        for overlay in self.overlays:
            receiving = self.chart_b if overlay.direction == "a_in_b" else self.chart_a
            source = self.chart_a if overlay.direction == "a_in_b" else self.chart_b
            if not receiving.house_cusps:
                raise ValueError("Overlay requires receiving houses")
            key_overlay = (overlay.direction, overlay.body)
            if key_overlay in seen:
                raise ValueError("Duplicate overlay")
            seen.add(key_overlay)
            expected_precision = (
                "date_sample"
                if source.precision == "date_sample"
                else "approximate"
                if "approximate" in {source.precision, receiving.precision}
                else "exact"
            )
            planet = next(p for p in source.planets if p.body == overlay.body)
            start = receiving.house_cusps[overlay.house - 1]
            end = receiving.house_cusps[overlay.house % 12]
            if (
                overlay.precision != expected_precision
                or (planet.longitude - start) % 360 >= (end - start) % 360
            ):
                raise ValueError("Inconsistent overlay")
        if len(self.overlays) != 10 * (
            bool(self.chart_a.house_cusps) + bool(self.chart_b.house_cusps)
        ):
            raise ValueError("Missing overlays")
        return self


def validate_chart(request: ChartInput, result: ChartFacts) -> None:
    expected = "date_sample" if request.accuracy == "unknown" else request.accuracy
    if result.precision != expected:
        raise ValueError("Chart precision differs from request")
    if result.house_cusps and (request.accuracy == "unknown" or request.latitude is None):
        raise ValueError("Unexpected houses")
    if ("approximate_date" in result.reasons) != request.date_approximate:
        raise ValueError("Date uncertainty differs from request")


def schema_document() -> dict[str, object]:
    return {
        "chart_request": ChartRequest.model_json_schema(),
        "chart_response": ChartResult.model_json_schema(),
        "synastry_request": SynastryRequest.model_json_schema(),
        "synastry_response": SynastryResult.model_json_schema(),
    }
