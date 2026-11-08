"""Synthetic MCP transport smoke check; never use real birth data here."""

import asyncio
from datetime import date
from uuid import uuid4

from oria_engine.astrology.client import FastMCPAstrologyClient
from oria_engine.astrology.contracts import NatalRequest
from oria_engine.astrology.linked import ChartInput, ChartRequest, SynastryRequest
from oria_engine.astrology.transits import TransitRequest


async def smoke() -> None:
    request = NatalRequest.model_validate(
        dict(
            timestamp_utc="2000-01-01T12:00:00Z",
            birth_time_accuracy="exact",
            latitude=51.5,
            longitude=0,
        )
    )
    client = FastMCPAstrologyClient("http://astrology-mcp:8000/mcp")
    chart = await client.calculate_natal_chart(request)
    assert len(chart.planets) == 10 and chart.availability.houses
    assert request.timestamp_utc is not None
    transits = await client.calculate_transits(
        TransitRequest.from_natal(chart, request.timestamp_utc)
    )
    assert len(transits.planets) == 10 and transits.availability.natal_aspects
    unknown = NatalRequest(
        birth_time_accuracy="unknown",
        local_birth_date=request.timestamp_utc.date(),
        latitude=51.5,
        longitude=0,
    )
    chart = await client.calculate_natal_chart(unknown)
    assert not chart.planets and chart.angles is None
    transits = await client.calculate_transits(
        TransitRequest.from_natal(chart, request.timestamp_utc)
    )
    assert len(transits.planets) == 10 and not transits.aspects
    assert not transits.availability.natal_aspects
    event_input = ChartInput(
        accuracy="exact",
        timestamp_utc=request.timestamp_utc,
        latitude=51.5,
        longitude=0,
    )
    event = await client.calculate_event_chart(
        ChartRequest(calculation_id=uuid4(), chart=event_input)
    )
    assert len(event.chart.planets) == 10 and len(event.chart.house_cusps) == 12
    comparison = await client.calculate_synastry(
        SynastryRequest(
            calculation_id=uuid4(),
            chart_a=event_input,
            chart_b=ChartInput(accuracy="unknown", calendar_date=date(1992, 6, 2)),
        )
    )
    assert comparison.chart_b.precision == "date_sample" and not comparison.chart_b.house_cusps
    assert len(comparison.overlays) == 10
    assert all(
        o.direction == "b_in_a" and o.precision == "date_sample" for o in comparison.overlays
    )
    print("Typed natal, transit, synastry and event MCP checks passed")


if __name__ == "__main__":
    asyncio.run(smoke())
