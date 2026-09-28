import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from astrology_mcp.server import create_server
from fastmcp import Client

from oria_engine.astrology.client import AstrologyUnavailable, FastMCPAstrologyClient
from oria_engine.astrology.contracts import NatalRequest


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
