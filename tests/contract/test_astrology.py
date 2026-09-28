import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest
from astrology_mcp.engine import CalculationUnavailable, aspects, calculate, house_for
from astrology_mcp.server import configure_service_logging, create_server
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from oria_engine.astrology.contracts import NatalRequest, NatalResult, Planet

ROOT = Path(__file__).resolve().parents[2]
KNOWN = dict(
    timestamp_utc="2000-01-01T12:00:00Z", birth_time_accuracy="exact", latitude=51.5, longitude=0
)


@pytest.mark.parametrize(
    "change",
    [
        {"user_id": "synthetic"},
        {"telegram_id": "synthetic"},
        {"timestamp_utc": "2000-01-01T12:00:00"},
        {"timestamp_utc": "2000-01-01T12:00:00+02:00"},
        {"latitude": 91},
        {"longitude": float("nan")},
        {"house_system": "W"},
        {"timestamp_utc": "1700-01-01T12:00:00Z"},
        {"birth_time_accuracy": "unknown"},
        {"contract_version": 2},
        {"local_birth_date": "2000-01-01"},
    ],
)
def test_invalid_request(change):
    with pytest.raises(ValidationError):
        NatalRequest.model_validate(KNOWN | change)


def test_unknown_time_and_approximate():
    request = NatalRequest(
        birth_time_accuracy="unknown", local_birth_date="2000-01-01", latitude=51.5, longitude=0
    )
    result = calculate(request)
    expected = json.loads((ROOT / "tests/contract/fixtures/unknown-natal.json").read_text())
    assert result.model_dump(mode="json") == expected
    assert not result.planets and not result.aspects and not result.house_cusps
    assert result.angles is None and result.availability.reasons == ("unknown_birth_time",)
    approximate = calculate(
        NatalRequest.model_validate(KNOWN | {"birth_time_accuracy": "approximate"})
    )
    assert approximate.availability.reasons == ("approximate_birth_time",)


def planet(body, longitude, speed):
    return Planet(
        body=body,
        longitude=longitude,
        sign="Aries",
        degree_in_sign=longitude % 30,
        longitude_velocity_deg_day=speed,
        retrograde=speed < 0,
    )


@pytest.mark.parametrize(
    ("a", "b", "speed", "orb", "applying"),
    [
        (359, 1, -1, 2, True),
        (359, 1, 1, 2, False),
        (0, 91.4, -0.42, 1.4, True),
        (0, 91.4, 0.42, 1.4, False),
        (0, 90, 1, 0, None),
        (0, 91, 0, 1, None),
        (0, 96, 1, 6, False),
    ],
)
def test_aspect_geometry(a, b, speed, orb, applying):
    result = aspects((planet("sun", a, 0), planet("moon", b, speed)))
    assert len(result) == 1
    assert result[0].orb == pytest.approx(orb)
    assert result[0].relative_velocity_deg_day == speed
    assert result[0].applying is applying
    assert result[0].time_to_exact_hours is None


def test_orb_boundary_and_cusp_wrap():
    assert not aspects((planet("sun", 0, 0), planet("moon", 96.0001, 1)))
    cusps = tuple((350 + i * 30) % 360 for i in range(12))
    assert house_for(350, cusps) == 1 and house_for(0, cusps) == 1
    assert house_for(20, cusps) == 2


def test_polar_houses_do_not_fall_back():
    result = calculate(NatalRequest.model_validate(KNOWN | {"latitude": 80}))
    assert result.planets and not result.house_cusps and result.angles is None
    assert all(p.house is None for p in result.planets)
    assert result.availability.reasons == ("houses_unsupported",)


def test_external_ephemeris_and_fallback_rejected(monkeypatch):
    import astrology_mcp.engine as engine

    monkeypatch.setenv("SE_EPHE_PATH", "/synthetic")
    with pytest.raises(CalculationUnavailable):
        calculate(NatalRequest.model_validate(KNOWN))
    monkeypatch.delenv("SE_EPHE_PATH")
    monkeypatch.setattr(
        engine.swe, "calc", lambda *args: ((0, 0, 0, 0, 0, 0), engine.swe.FLG_SWIEPH)
    )
    with pytest.raises(CalculationUnavailable):
        calculate(NatalRequest.model_validate(KNOWN))


async def test_mcp_contract_and_private_errors(capsys):
    configure_service_logging()
    server = create_server()
    async with Client(server) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["calculate_natal_chart"]
        result = await client.call_tool("calculate_natal_chart", {"request": KNOWN})
        chart = NatalResult.model_validate(result.structured_content)
        assert chart.availability.positions and len(chart.planets) == 10
        assert "2000" not in repr(chart)
        for arguments in (
            {"request": KNOWN | {"user_id": "secret-synthetic"}},
            {"request": KNOWN, "user_id": "secret-synthetic"},
        ):
            with pytest.raises(ToolError) as error:
                await client.call_tool("calculate_natal_chart", arguments)
            assert "secret-synthetic" not in str(error.value)
    captured = capsys.readouterr()
    assert "secret-synthetic" not in captured.err and "2000-01-01" not in captured.err


def test_published_schema_matches_source():
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/generate_astrology_schema.py"), "--check"], check=True
    )
    schema = json.loads((ROOT / "contracts/astrology/v1.json").read_text())
    assert schema["request"]["additionalProperties"] is False


def test_natal_against_standalone_swetest_reference():
    with (ROOT / "tests/contract/fixtures/natal-swetest.csv").open() as source:
        reference = {
            row[0].strip().lower(): (float(row[1]), float(row[2])) for row in csv.reader(source)
        }
    result = calculate(NatalRequest.model_validate(KNOWN))
    for planet in result.planets:
        longitude, speed = reference[planet.body]
        assert planet.longitude == pytest.approx(longitude, abs=1e-6, rel=0)
        assert planet.longitude_velocity_deg_day == pytest.approx(speed, abs=1e-6, rel=0)
        assert planet.retrograde == (speed < 0)
    for i, cusp in enumerate(result.house_cusps, 1):
        assert cusp == pytest.approx(reference[f"house {i:2}"][0], abs=1e-6, rel=0)
    assert result.angles.ascendant == pytest.approx(reference["ascendant"][0], abs=1e-6, rel=0)
    assert result.angles.midheaven == pytest.approx(reference["mc"][0], abs=1e-6, rel=0)


async def test_health_and_readiness(monkeypatch):
    import astrology_mcp.server as module
    import httpx

    app = create_server().http_app(stateless_http=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get("/healthz")).status_code == 200
        assert (await client.get("/readyz")).status_code == 200

        def unavailable():
            raise RuntimeError("synthetic-private-diagnostic")

        monkeypatch.setattr(module, "metadata", unavailable)
        response = await client.get("/readyz")
        assert response.status_code == 503 and "synthetic" not in response.text
