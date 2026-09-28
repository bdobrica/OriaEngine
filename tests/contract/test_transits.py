"""Transit geometry, pinned astronomy reference, and additive MCP contract."""

import csv
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from astrology_mcp.engine import calculate, calculate_transits
from astrology_mcp.server import create_server
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from oria_engine.astrology.client import FastMCPAstrologyClient
from oria_engine.astrology.contracts import NatalRequest
from oria_engine.astrology.transits import TransitRequest, TransitResult
from tests.contract.test_astrology import KNOWN, ROOT

TARGET = datetime(2000, 1, 1, 12, tzinfo=UTC)


def request(accuracy="exact", target=TARGET):
    inputs = KNOWN | {"birth_time_accuracy": accuracy}
    if accuracy == "unknown":
        inputs.pop("timestamp_utc")
        inputs["local_birth_date"] = "2000-01-01"
    natal = calculate(NatalRequest.model_validate(inputs))
    return TransitRequest.from_natal(natal, target)


def test_transits_against_standalone_reference_and_fixed_natal():
    result = calculate_transits(request())
    with (ROOT / "tests/contract/fixtures/natal-swetest.csv").open() as source:
        reference = {
            row[0].strip().lower(): (float(row[1]), float(row[2])) for row in csv.reader(source)
        }
    for p in result.planets:
        longitude, speed = reference[p.body]
        assert p.longitude == pytest.approx(longitude, abs=1e-6, rel=0)
        assert p.longitude_velocity_deg_day == pytest.approx(speed, abs=1e-6, rel=0)
        assert p.retrograde == (speed < 0)
        assert p.house is None
    # Same-body relationships are meaningful, and the natal body never moves.
    returns = [a for a in result.aspects if a.body_a == a.body_b]
    assert len(returns) == 10
    for a in returns:
        assert a.name == "conjunction" and a.orb == 0 and a.applying is None
        assert a.relative_velocity_deg_day == pytest.approx(reference[a.body_b][1], abs=1e-6)
        assert a.time_to_exact_hours is None
    assert result.metadata.time_to_exact_method == "unavailable"


def test_transit_motion_matches_finite_difference():
    req = request(target=datetime(2026, 9, 28, 12, tzinfo=UTC))
    result = calculate_transits(req)
    later = calculate_transits(
        req.model_copy(
            update={
                "target_timestamp_utc": req.target_timestamp_utc + timedelta(minutes=1),
            }
        )
    )
    future = {(a.body_a, a.body_b): a for a in later.aspects}
    assert any(a.applying is True for a in result.aspects)
    assert any(a.applying is False for a in result.aspects)
    for a in result.aspects:
        after = future.get((a.body_a, a.body_b))
        if after is not None and after.name == a.name and a.orb > 0.1:
            assert a.applying == (after.orb < a.orb)
        moving = next(p for p in result.planets if p.body == a.body_b)
        assert a.relative_velocity_deg_day == moving.longitude_velocity_deg_day


@pytest.mark.parametrize("accuracy", ["exact", "approximate", "unknown"])
async def test_typed_mcp_transits_and_privacy(accuracy):
    req = request(accuracy)
    serialized = req.model_dump_json()
    for forbidden in ("birth_date", "birth_place", "latitude", "longitude_velocity", "user_id"):
        assert forbidden not in serialized
    assert "2000" not in repr(req)
    with patch("oria_engine.astrology.client.Client", return_value=Client(create_server())):
        result = await FastMCPAstrologyClient("http://test/mcp").calculate_transits(req)
    assert len(result.planets) == 10
    assert result.availability.natal_aspects == (accuracy != "unknown")
    if accuracy == "unknown":
        assert not result.aspects
        assert result.availability.reasons == ("unknown_birth_time",)
    if accuracy == "approximate":
        assert result.availability.reasons == ("approximate_birth_time",)


@pytest.mark.parametrize(
    "change",
    [
        {"target_timestamp_utc": "2026-01-01T12:00:00"},
        {"target_timestamp_utc": "2026-01-01T12:00:00+02:00"},
        {"target_timestamp_utc": "1799-01-01T12:00:00Z"},
        {"target_timestamp_utc": "2400-01-01T12:00:00Z"},
        {"natal_positions": []},
        {"birth_time_accuracy": "unknown"},
        {"latitude": 0},
        {"user_id": "synthetic-private"},
        {"contract_version": 2},
    ],
)
def test_invalid_transit_requests(change):
    with pytest.raises(ValidationError):
        TransitRequest.model_validate(request().model_dump() | change)


def test_invalid_result_availability():
    result = calculate_transits(request("unknown")).model_dump()
    result["availability"]["natal_aspects"] = True
    with pytest.raises(ValidationError):
        TransitResult.model_validate(result)


async def test_transit_private_errors():
    async with Client(create_server()) as client:
        for arguments in (
            {"request": request().model_dump(mode="json") | {"user_id": "synthetic-secret"}},
            {"request": request().model_dump(mode="json"), "user_id": "synthetic-secret"},
        ):
            with pytest.raises(ToolError) as error:
                await client.call_tool("calculate_transits", arguments)
            assert "synthetic-secret" not in str(error.value)
