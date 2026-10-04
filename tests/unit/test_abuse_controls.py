import asyncio
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from oria_engine.astrology.http import (
    MAX_RESPONSE_BYTES,
    BoundedStream,
    ResponseTooLarge,
    bound_response,
    bounded_http_client,
)
from oria_engine.config import Settings
from oria_engine.context.contracts import ConversationRequest
from oria_engine.context.service import ConversationContext
from oria_engine.queue.limits import UNAVAILABLE_REPLY, AdmissionRejected, InboundLimits


@pytest.mark.parametrize("field", ["inbound_rate_per_minute", "queued_jobs_per_user"])
@pytest.mark.parametrize("value", [0, -1, 1000])
def test_limits_cannot_be_disabled_by_invalid_settings(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize(
    "provider,sender",
    [("telegram", "name"), ("telegram", "١"), ("other", "42"), ("telegram", "42:private")],
)
def test_counter_keys_reject_untrusted_strings(provider, sender):
    with pytest.raises(ValueError, match="Unsupported admission identity"):
        InboundLimits.key(provider, sender)


async def test_counters_and_notices_only_use_numeric_identity():
    redis = Mock()
    redis.eval.return_value = 1
    redis.set.return_value = True
    limits = InboundLimits(redis, Settings(_env_file=None))
    assert await limits.admit("telegram", "42")
    assert redis.eval.call_args.args[2:] == ("oria:abuse:telegram:42:rate", 20)
    with pytest.raises(AdmissionRejected) as error:
        await limits.reject("telegram", "42", "Fixed notice")
    assert error.value.reply == "Fixed notice"
    assert redis.set.call_args.kwargs == {"nx": True, "ex": 60}
    redis.set.return_value = None
    with pytest.raises(AdmissionRejected) as error:
        await limits.reject("telegram", "42", "Fixed notice")
    assert error.value.reply is None


async def test_disable_switch_prevents_generation_memory_and_session_mutation():
    provider, session = AsyncMock(), AsyncMock()
    context = ConversationContext(provider, "test", enabled=False)
    result = await context.respond(session, uuid4(), ConversationRequest(filtered_message="Hi"))
    assert result.text == UNAVAILABLE_REPLY
    await context.remember(session, uuid4(), "concise_readings")
    assert not provider.mock_calls and not session.mock_calls


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("content_type", ["application/json", "text/event-stream"])
async def test_mcp_stream_bound_before_json_or_sse_buffering(content_type):
    source = Chunks([b"x" * MAX_RESPONSE_BYTES, b"private"])
    response = httpx.Response(200, headers={"Content-Type": content_type}, stream=source)
    await bound_response(response)
    stream = response.aiter_bytes()
    assert len(await anext(stream)) == MAX_RESPONSE_BYTES
    with pytest.raises(ResponseTooLarge) as error:
        await anext(stream)
    assert "private" not in str(error.value)
    await response.aclose()
    assert source.closed


async def test_mcp_compression_cannot_bypass_response_limit():
    source = Chunks([b"compressed"])
    response = httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=source)
    with pytest.raises(ResponseTooLarge):
        await bound_response(response)
    assert source.closed


async def test_mcp_stream_cancellation_propagates():
    class Cancel(Chunks):
        async def __aiter__(self):
            raise asyncio.CancelledError
            yield b"unreachable"

    with pytest.raises(asyncio.CancelledError):
        await anext(BoundedStream(Cancel([])).__aiter__())


async def test_mcp_factory_bounds_real_httpx_stream_and_closes_resources():
    source = Chunks([b"x" * (MAX_RESPONSE_BYTES + 1)])

    def handle(request):
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(200, stream=source)

    async with bounded_http_client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ResponseTooLarge):
            await client.get("http://synthetic.invalid/mcp")
    assert source.closed
