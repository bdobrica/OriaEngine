import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from oria_engine.astrology.contracts import NatalResult
from oria_engine.config import Settings
from oria_engine.context.contracts import (
    MEMORY_TEXT,
    ContextScope,
    ContextUnavailable,
    ConversationRequest,
)
from oria_engine.context.second_context import SecondContextProvider
from tests.support.second_context import SecondContextStub


def provider(handler, **kwargs):
    return SecondContextProvider(
        Settings(
            _env_file=None,
            second_context_base_url="http://context.invalid/prefix",
            second_context_bearer_token="synthetic-secret",
        ),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def scope():
    return ContextScope(user_id=uuid4(), session_id=uuid4())


async def test_continuity_scoping_auth_and_no_profile_memory():
    stub = SecondContextStub(token="synthetic-secret")
    client = provider(stub)
    first, second = scope(), scope()
    request = ConversationRequest(filtered_message="Explain a theme.")
    try:
        assert (await client.respond(first, request)).text == "No prior preference."
        await client.remember(first, "concise_readings")
        assert (await client.respond(first, request)).text == MEMORY_TEXT["concise_readings"]
        assert (await client.respond(second, request)).text == "No prior preference."
        assert stub.sessions == {
            str(first.session_id): str(first.user_id),
            str(second.session_id): str(second.user_id),
        }
        with pytest.raises(ContextUnavailable):
            await client.respond(
                ContextScope(user_id=second.user_id, session_id=first.session_id), request
            )
        for sent in stub.requests:
            assert sent.headers["Authorization"] == "Bearer synthetic-secret"
            assert sent.url.path.startswith("/prefix/")
        memory = json.loads(stub.requests[1].content)
        assert memory["raw_text"] == MEMORY_TEXT["concise_readings"]
        assert set(memory) == {"user", "raw_text", "summary", "type", "source", "metadata"}
        with pytest.raises(ValueError, match="Unsupported"):
            await client.remember(first, "1990-01-01 Bucharest")
    finally:
        await client.aclose()


async def test_subject_bound_bearer_cannot_select_another_user():
    first = scope()
    stub = SecondContextStub(token="synthetic-secret", subject=str(first.user_id))
    client = provider(stub)
    try:
        await client.respond(first, ConversationRequest(filtered_message="Hello"))
        with pytest.raises(ContextUnavailable):
            await client.respond(scope(), ConversationRequest(filtered_message="Hello"))
        assert len(stub.sessions) == 1
    finally:
        await client.aclose()


async def test_no_auth_header_when_disabled():
    stub = SecondContextStub()
    client = SecondContextProvider(Settings(_env_file=None), transport=httpx.MockTransport(stub))
    try:
        await client.respond(scope(), ConversationRequest(filtered_message="Hello"))
        assert "Authorization" not in stub.requests[0].headers
    finally:
        await client.aclose()


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500, 503])
async def test_http_errors_never_echo_or_retry_ambiguous_mutations(status):
    calls = []

    def fail(request):
        calls.append(request)
        return httpx.Response(
            status,
            text="sensitive downstream payload",
            headers={"Location": "https://untrusted.invalid"},
        )

    client = provider(fail)
    try:
        with pytest.raises(ContextUnavailable) as error:
            await client.respond(scope(), ConversationRequest(filtered_message="private"))
        assert "private" not in str(error.value)
        assert "sensitive" not in str(error.value)
        assert len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.WriteError, httpx.ConnectTimeout])
async def test_only_connection_failures_retry(failure):
    calls = []

    def fail(request):
        calls.append(request)
        raise failure("private upstream exception")

    client = provider(fail)
    try:
        with pytest.raises(ContextUnavailable) as error:
            await client.respond(scope(), ConversationRequest(filtered_message="Hello"))
        assert "private" not in str(error.value)
        assert len(calls) == (3 if failure is httpx.ConnectTimeout else 1)
    finally:
        await client.aclose()


@pytest.mark.parametrize("body", [b"not-json", b"{}", b"x" * 262145])
async def test_malformed_and_oversized_responses(body):
    client = provider(lambda request: httpx.Response(200, content=body))
    try:
        with pytest.raises(ContextUnavailable):
            await client.respond(scope(), ConversationRequest(filtered_message="Hello"))
    finally:
        await client.aclose()


@pytest.mark.parametrize("field", ["session_id", "user_external_id", "status", "output_text"])
async def test_response_scope_and_typed_parsing(field):
    stub = SecondContextStub()

    def wrong(request):
        body = stub(request).json()
        if field == "session_id":
            body["metadata"][field] = str(uuid4())
        elif field == "user_external_id":
            body["metadata"]["context_packet"][field] = str(uuid4())
        else:
            body[field] = "" if field == "output_text" else "in_progress"
        return httpx.Response(200, json=body)

    client = provider(wrong)
    try:
        with pytest.raises(ContextUnavailable):
            await client.respond(scope(), ConversationRequest(filtered_message="Hello"))
    finally:
        await client.aclose()


async def test_deadline_and_cancellation():
    async def wait(request):
        await asyncio.sleep(10)

    client = provider(wait, timeout=0.02)
    try:
        with pytest.raises(ContextUnavailable):
            await client.respond(scope(), ConversationRequest(filtered_message="Hello"))
        task = asyncio.create_task(
            client.respond(scope(), ConversationRequest(filtered_message="Hello"))
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await client.aclose()


async def test_service_namespace_continuity_and_purge():
    stub = SecondContextStub(token="synthetic-secret", namespace="oria")
    client = SecondContextProvider(
        Settings(
            _env_file=None,
            second_context_subject_namespace="oria",
            second_context_bearer_token="synthetic-secret",
        ),
        transport=httpx.MockTransport(stub),
    )
    first, second = scope(), scope()
    request = ConversationRequest(filtered_message="Hello")
    try:
        await client.remember(first, "concise_readings")
        await client.remember(second, "less_mystical_language")
        assert "concise" in (await client.respond(first, request)).text
        assert "mystical" in (await client.respond(second, request)).text
        for _ in range(2):
            await client.purge(first.user_id)
        with pytest.raises(ContextUnavailable):
            await client.respond(first, request)
        assert "mystical" in (await client.respond(second, request)).text
        assert str(first.session_id) not in stub.sessions
        assert f"oria:{first.user_id}" not in stub.memories
        for sent in stub.requests:
            assert sent.headers["X-SecondContext-Subject"] == json.loads(sent.content)["user"]
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "status,body",
    [
        (404, {}),
        (503, {"status": "completed"}),
        (200, {}),
        (200, {"contract_version": 1, "user": "foreign", "status": "completed"}),
        (200, {"contract_version": 1, "user": "foreign", "status": "pending"}),
        (200, {"contract_version": 2, "user": "foreign", "status": "completed"}),
    ],
)
async def test_purge_requires_explicit_scoped_completion(status, body):
    client = provider(lambda request: httpx.Response(status, json=body))
    try:
        with pytest.raises(ContextUnavailable):
            await client.purge(uuid4())
    finally:
        await client.aclose()


async def test_purge_retry_after_downstream_failure():
    target = uuid4()
    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(
            200, json={"contract_version": 1, "user": str(target), "status": "completed"}
        )

    client = provider(handle)
    try:
        with pytest.raises(ContextUnavailable):
            await client.purge(target)
        await client.purge(target)
        assert calls == [{"user": str(target)}] * 2
    finally:
        await client.aclose()


async def test_calculated_facts_are_instructions_only():
    from pathlib import Path

    natal = NatalResult.model_validate_json(
        (Path(__file__).parent / "fixtures/unknown-natal.json").read_text()
    )
    stub = SecondContextStub()
    client = provider(stub)
    try:
        await client.respond(
            scope(), ConversationRequest(filtered_message="Hello", natal_facts=natal)
        )
        body = json.loads(stub.requests[0].content)
        assert natal.model_dump_json() in body["instructions"]
        assert body["input"] == "Hello"
        assert "planets" not in body["metadata"]
        assert "birth_date" not in body["instructions"]
        with pytest.raises(ValidationError):
            ConversationRequest(filtered_message="Hello", birth_date="1990-01-01")
        assert "Hello" not in repr(ConversationRequest(filtered_message="Hello"))
    finally:
        await client.aclose()


async def test_transit_facts_are_instructions_only():
    from astrology_mcp.engine import calculate_transits

    from tests.contract.test_transits import request

    facts = calculate_transits(request())
    stub = SecondContextStub()
    client = provider(stub)
    try:
        await client.respond(
            scope(),
            ConversationRequest(
                filtered_message="Explain today's transits",
                goal="current_transits",
                transit_facts=facts,
            ),
        )
        assert len(stub.requests) == 1
        body = json.loads(stub.requests[0].content)
        assert facts.model_dump_json() in body["instructions"]
        assert "Calculated natal facts" not in body["instructions"]
        assert body["input"] == "Explain today's transits"
        assert "planets" not in json.dumps(body["metadata"])
        assert "birth_date" not in body["instructions"]
        assert "latitude" not in body["instructions"]
    finally:
        await client.aclose()
