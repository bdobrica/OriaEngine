"""Typed, bounded MCP boundary; exceptions never expose requests or responses."""

import asyncio
from typing import Protocol

from fastmcp import Client

from oria_engine.astrology.contracts import NatalRequest, NatalResult


class AstrologyUnavailable(Exception):
    """Calculation failed; the confirmed profile can be retried."""


class AstrologyClient(Protocol):
    async def calculate_natal_chart(self, request: NatalRequest) -> NatalResult: ...


class FastMCPAstrologyClient:
    def __init__(self, url: str, *, timeout: float = 20) -> None:
        self.url = url
        self.timeout = timeout

    async def calculate_natal_chart(self, request: NatalRequest) -> NatalResult:
        try:
            async with asyncio.timeout(self.timeout):
                async with Client(self.url, timeout=self.timeout) as client:
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
