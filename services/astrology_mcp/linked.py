"""Linked calculations share the pinned astronomy, without changing natal v1."""

from datetime import UTC, datetime, time

from oria_engine.astrology.contracts import NatalRequest
from oria_engine.astrology.linked import (
    ChartFacts,
    ChartInput,
    ChartRequest,
    ChartResult,
    CrossAspect,
    LinkedMetadata,
    Overlay,
    SynastryRequest,
    SynastryResult,
)

from .engine import LOCK, TARGETS, calculate, house_for, metadata, positions


def chart(request: ChartInput) -> ChartFacts:
    request = ChartInput.model_validate(request)
    metadata()
    if request.accuracy != "unknown" and request.latitude is not None:
        assert request.longitude is not None
        natal = calculate(
            NatalRequest(
                timestamp_utc=request.timestamp_utc,
                birth_time_accuracy=request.accuracy,
                latitude=request.latitude,
                longitude=request.longitude,
            )
        )
        return ChartFacts(
            precision=request.accuracy,
            planets=natal.planets,
            house_cusps=natal.house_cusps,
            angles=natal.angles,
            reasons=(
                *(("approximate_time",) if request.accuracy == "approximate" else ()),
                *(("houses_unsupported",) if not natal.house_cusps else ()),
            ),
        )
    instant = request.timestamp_utc
    if request.accuracy == "unknown":
        assert request.calendar_date is not None
        instant = datetime.combine(request.calendar_date, time(12), tzinfo=UTC)
    assert instant is not None
    with LOCK:
        _, planets = positions(instant)
    reasons = []
    if request.accuracy == "unknown":
        reasons.append("date_only_sample")
        if request.date_approximate:
            reasons.append("approximate_date")
    elif request.accuracy == "approximate":
        reasons.append("approximate_time")
    if request.latitude is None:
        reasons.append("place_unknown")
    return ChartFacts.model_validate(
        dict(
            precision="date_sample" if request.accuracy == "unknown" else request.accuracy,
            planets=planets,
            reasons=reasons,
        )
    )


def calculate_event_chart(request: ChartRequest) -> ChartResult:
    request = ChartRequest.model_validate(request)
    return ChartResult(
        calculation_id=request.calculation_id,
        chart=chart(request.chart),
        metadata=LinkedMetadata(astronomy=metadata()),
    )


def calculate_synastry(request: SynastryRequest) -> SynastryResult:
    request = SynastryRequest.model_validate(request)
    a, b = chart(request.chart_a), chart(request.chart_b)
    aspects = []
    for p in a.planets:
        for q in b.planets:
            separation = abs((q.longitude - p.longitude + 180) % 360 - 180)
            for name, target in TARGETS:
                if abs(separation - target) <= 6:
                    aspects.append(
                        CrossAspect.model_validate(
                            dict(
                                body_a=p.body,
                                body_b=q.body,
                                name=name,
                                target_angle=target,
                                angular_separation=separation,
                                orb=abs(separation - target),
                            )
                        )
                    )
    overlays = []
    for direction, source, target_chart in (("a_in_b", a, b), ("b_in_a", b, a)):
        if not target_chart.house_cusps:
            continue
        precision = (
            "date_sample"
            if source.precision == "date_sample"
            else "approximate"
            if "approximate" in {source.precision, target_chart.precision}
            else "exact"
        )
        for p in source.planets:
            overlays.append(
                Overlay.model_validate(
                    dict(
                        direction=direction,
                        body=p.body,
                        house=house_for(p.longitude, target_chart.house_cusps),
                        precision=precision,
                    )
                )
            )
    return SynastryResult(
        calculation_id=request.calculation_id,
        chart_a=a,
        chart_b=b,
        aspects=tuple(aspects),
        overlays=tuple(overlays),
        metadata=LinkedMetadata(astronomy=metadata()),
    )
