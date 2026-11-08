"""Synthetic linked astronomy, precision and additive wire compatibility."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from astrology_mcp.engine import calculate
from astrology_mcp.linked import calculate_event_chart, calculate_synastry
from astrology_mcp.server import create_server
from fastmcp import Client
from pydantic import ValidationError

from oria_engine.astrology.client import AstrologyUnavailable, FastMCPAstrologyClient
from oria_engine.astrology.contracts import NatalRequest
from oria_engine.astrology.linked import (
    ChartInput,
    ChartRequest,
    SynastryRequest,
    SynastryResult,
)


def known(**changes):
    return ChartInput.model_validate(
        dict(
            accuracy="exact",
            timestamp_utc="2000-01-01T12:00:00Z",
            latitude=51.5,
            longitude=0,
        )
        | changes
    )


@pytest.mark.parametrize(
    "change",
    [
        {"user_id": str(uuid4())},
        {"house_system": "W"},
        {"timestamp_utc": "2000-01-01"},
        {"timestamp_utc": "2000-01-01T12:00:00+01:00"},
        {"latitude": float("nan")},
        {"calendar_date": "2000-01-01"},
        {"accuracy": "unknown"},
        {"timestamp_utc": "1799-01-01T12:00:00Z"},
        {"longitude": None},
    ],
)
def test_input_is_closed_bounded_and_has_no_invented_time(change):
    with pytest.raises(ValidationError):
        known(**change)


def test_exact_chart_reuses_published_astronomy():
    source = known()
    result = calculate_event_chart(ChartRequest(calculation_id=uuid4(), chart=source))
    legacy = calculate(
        NatalRequest(
            timestamp_utc=source.timestamp_utc,
            birth_time_accuracy="exact",
            latitude=source.latitude,
            longitude=source.longitude,
        )
    )
    assert result.chart.planets == legacy.planets
    assert result.chart.house_cusps == legacy.house_cusps
    assert result.chart.angles == legacy.angles
    assert result.metadata.engine_version == "oria-linked-1"


def test_birthday_sample_is_explicit_without_changing_unknown_natal():
    date_only = ChartInput(accuracy="unknown", calendar_date="2000-01-01")
    sample = calculate_event_chart(ChartRequest(calculation_id=uuid4(), chart=date_only)).chart
    exact = calculate_event_chart(ChartRequest(calculation_id=uuid4(), chart=known())).chart
    assert sample.precision == "date_sample"
    assert "date_only_sample" in sample.reasons and "place_unknown" in sample.reasons
    assert not sample.house_cusps and sample.angles is None
    assert [p.longitude for p in sample.planets] == [p.longitude for p in exact.planets]
    assert all(p.house is None for p in sample.planets)
    legacy = calculate(
        NatalRequest(
            birth_time_accuracy="unknown",
            local_birth_date="2000-01-01",
            latitude=0,
            longitude=0,
        )
    )
    assert not legacy.planets


@pytest.mark.parametrize("accuracy", ["exact", "approximate"])
def test_comparison_geometry_overlays_and_precision(accuracy):
    a, b = known(accuracy=accuracy), known(timestamp_utc="1992-06-02T08:30:00Z")
    result = calculate_synastry(SynastryRequest(calculation_id=uuid4(), chart_a=a, chart_b=b))
    assert len(result.overlays) == 20
    assert all(o.precision == accuracy for o in result.overlays)
    assert {o.direction for o in result.overlays} == {"a_in_b", "b_in_a"}
    for aspect in result.aspects:
        p = next(p for p in result.chart_a.planets if p.body == aspect.body_a)
        q = next(p for p in result.chart_b.planets if p.body == aspect.body_b)
        expected = min(abs(p.longitude - q.longitude), 360 - abs(p.longitude - q.longitude))
        assert aspect.angular_separation == pytest.approx(expected)
        assert aspect.orb == pytest.approx(abs(expected - aspect.target_angle))
        assert "applying" not in aspect.model_dump()  # Different dates are static geometry.
    reverse = calculate_synastry(SynastryRequest(calculation_id=uuid4(), chart_a=b, chart_b=a))
    assert {(a.body_a, a.body_b, a.name) for a in result.aspects} == {
        (a.body_b, a.body_a, a.name) for a in reverse.aspects
    }


def test_sampled_overlay_never_creates_receiving_houses():
    sample = ChartInput(accuracy="unknown", calendar_date="1992-06-02")
    result = calculate_synastry(
        SynastryRequest(calculation_id=uuid4(), chart_a=known(), chart_b=sample)
    )
    assert len(result.overlays) == 10
    assert all(o.direction == "b_in_a" and o.precision == "date_sample" for o in result.overlays)
    for invalid in (
        {"overlays": []},
        {"aspects": []},
        {"overlays": [o.model_dump() | {"precision": "exact"} for o in result.overlays]},
    ):
        with pytest.raises(ValidationError):
            SynastryResult.model_validate(result.model_dump() | invalid)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"latitude": None, "longitude": None}, "place_unknown"),
        ({"latitude": 80}, "houses_unsupported"),
    ],
)
def test_unavailable_houses_are_not_replaced(change, reason):
    result = calculate_event_chart(ChartRequest(calculation_id=uuid4(), chart=known(**change)))
    assert not result.chart.house_cusps and result.chart.angles is None
    assert reason in result.chart.reasons


async def test_real_adapter_and_mcp_roundtrip():
    request = SynastryRequest(
        calculation_id=uuid4(),
        chart_a=known(),
        chart_b=ChartInput(accuracy="unknown", calendar_date="1992-06-02"),
    )
    client = FastMCPAstrologyClient("http://unused/mcp")
    with patch("oria_engine.astrology.client.Client", return_value=Client(create_server())):
        result = await client.calculate_synastry(request)
    assert result == calculate_synastry(request)
    event = ChartRequest(calculation_id=uuid4(), chart=known())
    with patch("oria_engine.astrology.client.Client", return_value=Client(create_server())):
        assert await client.calculate_event_chart(event) == calculate_event_chart(event)
    # Result packets contain no raw dates, times or coordinates.
    wire = result.model_dump_json()
    assert "1992-06-02" not in wire and "timestamp_utc" not in wire and "latitude" not in wire
    assert repr(result) == "SynastryResult(<redacted>)"


async def test_adapter_rejects_mismatched_request_and_propagates_cancellation():
    import asyncio
    from unittest.mock import AsyncMock

    request = ChartRequest(calculation_id=uuid4(), chart=known())
    result = calculate_event_chart(request).model_copy(update={"calculation_id": uuid4()})
    remote = AsyncMock()
    remote.__aenter__.return_value = remote
    remote.call_tool.return_value.is_error = False
    remote.call_tool.return_value.structured_content = result.model_dump(mode="json")
    with (
        patch("oria_engine.astrology.client.Client", return_value=remote),
        pytest.raises(AstrologyUnavailable),
    ):
        await FastMCPAstrologyClient("http://unused/mcp").calculate_event_chart(request)
    remote.__aenter__.side_effect = asyncio.CancelledError
    with (
        patch("oria_engine.astrology.client.Client", return_value=remote),
        pytest.raises(asyncio.CancelledError),
    ):
        await FastMCPAstrologyClient("http://unused/mcp").calculate_event_chart(request)
