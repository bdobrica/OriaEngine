"""Synthetic MCP transport smoke check; never use real birth data here."""

import asyncio

from oria_engine.astrology.client import FastMCPAstrologyClient
from oria_engine.astrology.contracts import NatalRequest
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
    print("Typed natal and transit MCP checks passed")


if __name__ == "__main__":
    asyncio.run(smoke())
