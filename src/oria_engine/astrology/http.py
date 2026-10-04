"""Bound MCP HTTP/SSE bytes before protocol JSON parsing, without diagnostic payloads."""

from collections.abc import AsyncIterator
from typing import Any

import httpx

MAX_RESPONSE_BYTES = 256 * 1024


class ResponseTooLarge(Exception):
    pass


class BoundedStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream) -> None:
        self.stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        size = 0
        async for chunk in self.stream:
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ResponseTooLarge("Calculation response limit reached")
            yield chunk

    async def aclose(self) -> None:
        await self.stream.aclose()


async def bound_response(response: httpx.Response) -> None:
    # The controlled MCP service sends uncompressed JSON/SSE. Refuse compression
    # so a small compressed body cannot expand past the bound inside HTTPX.
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        await response.aclose()
        raise ResponseTooLarge("Unsupported calculation response encoding")
    if not isinstance(response.stream, httpx.AsyncByteStream):
        raise ResponseTooLarge("Unsupported calculation response stream")
    response.stream = BoundedStream(response.stream)


def bounded_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
    **kwargs: Any,
) -> httpx.AsyncClient:
    kwargs["follow_redirects"] = False
    kwargs["trust_env"] = False
    kwargs["headers"] = {**(headers or {}), "Accept-Encoding": "identity"}
    kwargs["timeout"] = timeout or httpx.Timeout(20, connect=3)
    kwargs["auth"] = auth
    kwargs["event_hooks"] = {"response": [bound_response]}
    return httpx.AsyncClient(**kwargs)
