"""Typed, bounded MCP boundary; exceptions never expose requests or responses."""

import asyncio
from typing import Protocol

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from oria_engine.astrology.contracts import NatalRequest, NatalResult
from oria_engine.astrology.http import bounded_http_client
from oria_engine.astrology.transits import TransitRequest, TransitResult


class AstrologyUnavailable(Exception):
    """Calculation failed; the confirmed profile can be retried."""


class AstrologyClient(Protocol):
    async def calculate_natal_chart(self, request: NatalRequest) -> NatalResult: ...

    async def calculate_transits(self, request: TransitRequest) -> TransitResult: ...


class FastMCPAstrologyClient:
    def __init__(self, url: str, *, timeout: float = 20) -> None:
        self.url = url
        self.timeout = timeout

    def transport(self) -> StreamableHttpTransport:
        return StreamableHttpTransport(self.url, httpx_client_factory=bounded_http_client)

    async def calculate_transits(self, request: TransitRequest) -> TransitResult:
        try:
            async with asyncio.timeout(self.timeout):
                async with Client(self.transport(), timeout=self.timeout) as client:
                    response = await client.call_tool(
                        "calculate_transits", {"request": request.model_dump(mode="json")}
                    )
                    if response.is_error:
                        raise AstrologyUnavailable()
                    result = TransitResult.model_validate(response.structured_content)
                    if (
                        result.birth_time_accuracy != request.birth_time_accuracy
                        or result.target_timestamp_utc != request.target_timestamp_utc
                    ):
                        raise AstrologyUnavailable()
                    return result
        except Exception:
            raise AstrologyUnavailable("Transit calculation temporarily unavailable") from None

    async def calculate_natal_chart(self, request: NatalRequest) -> NatalResult:
        try:
            async with asyncio.timeout(self.timeout):
                async with Client(self.transport(), timeout=self.timeout) as client:
                    response = await client.call_tool(
                        "calculate_natal_chart", {"request": request.model_dump(mode="json")}
                    )
                    if response.is_error:
                        raise AstrologyUnavailable()
                    result = NatalResult.model_validate(response.structured_content)
                    if result.birth_time_accuracy != request.birth_time_accuracy:
                        raise AstrologyUnavailable()
                    return result
        except Exception:
            raise AstrologyUnavailable("Chart calculation temporarily unavailable") from None
