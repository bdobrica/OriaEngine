import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from astrology_mcp.server import create_server
from fastmcp import Client

from oria_engine.astrology.client import AstrologyUnavailable, FastMCPAstrologyClient
from oria_engine.astrology.contracts import NatalRequest
from oria_engine.astrology.transits import TransitRequest


def request():
    return NatalRequest.model_validate(
        dict(
            timestamp_utc="2000-01-01T12:00:00Z",
            birth_time_accuracy="exact",
            latitude=51.5,
            longitude=0,
        )
    )


async def test_adapter_real_mcp_protocol():
    with patch("oria_engine.astrology.client.Client", return_value=Client(create_server())):
        result = await FastMCPAstrologyClient("http://test/mcp").calculate_natal_chart(request())
        assert len(result.planets) == 10


@pytest.mark.parametrize("failure", ["malformed", "error", "timeout"])
async def test_adapter_safe_errors(failure):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.call_tool.return_value.is_error = failure == "error"
    client.call_tool.return_value.structured_content = {"private": "synthetic-private"}
    if failure == "timeout":

        async def slow(*args, **kwargs):
            await asyncio.sleep(10)

        client.call_tool.side_effect = slow
    with (
        patch("oria_engine.astrology.client.Client", return_value=client),
        pytest.raises(AstrologyUnavailable) as exc,
    ):
        await FastMCPAstrologyClient("http://test/mcp", timeout=0.01).calculate_natal_chart(
            request()
        )
    assert "synthetic-private" not in str(exc.value)


@pytest.mark.parametrize("failure", ["malformed", "error", "timeout", "target", "accuracy"])
async def test_transit_adapter_safe_errors(failure):
    from datetime import timedelta

    from astrology_mcp.engine import calculate, calculate_transits

    req = TransitRequest.from_natal(calculate(request()), request().timestamp_utc)
    result = calculate_transits(req).model_dump(mode="json")
    if failure == "target":
        result["target_timestamp_utc"] = req.target_timestamp_utc + timedelta(days=1)
    elif failure == "accuracy":
        result["birth_time_accuracy"] = "approximate"
        result["availability"]["reasons"] = ["approximate_birth_time"]
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.call_tool.return_value.is_error = failure == "error"
    client.call_tool.return_value.structured_content = (
        {"private": "synthetic-private"} if failure == "malformed" else result
    )
    if failure == "timeout":

        async def slow(*args, **kwargs):
            await asyncio.sleep(10)

        client.call_tool.side_effect = slow
    with (
        patch("oria_engine.astrology.client.Client", return_value=client),
        pytest.raises(AstrologyUnavailable) as error,
    ):
        await FastMCPAstrologyClient("http://test/mcp", timeout=0.01).calculate_transits(req)
    assert "synthetic-private" not in str(error.value)


async def test_transit_adapter_propagates_cancellation():
    from astrology_mcp.engine import calculate

    req = TransitRequest.from_natal(calculate(request()), request().timestamp_utc)
    client = AsyncMock()
    client.__aenter__.side_effect = asyncio.CancelledError
    with (
        patch("oria_engine.astrology.client.Client", return_value=client),
        pytest.raises(asyncio.CancelledError),
    ):
        await FastMCPAstrologyClient("http://test/mcp").calculate_transits(req)
