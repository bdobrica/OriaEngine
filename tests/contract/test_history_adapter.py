"""Consumer wire tests with synthetic HTTP, independent of provider implementation types."""

import asyncio
import copy
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from oria_engine.config import Settings
from oria_engine.context.contracts import ContextScope, ContextUnavailable, ConversationRequest
from oria_engine.context.history import (
    FINALIZE_REQUEST,
    HISTORY_ERROR_STATUS,
    RECEIPT,
    AcceptLocal,
    HistoryCapabilities,
    HistoryCapabilitiesRequest,
    HistoryFailure,
    HistoryUnsupported,
    PreparedHistoryTurn,
)
from oria_engine.context.second_context import SecondContextProvider
from tests.contract.test_history_schema import CASES, validator


def example(name):
    return copy.deepcopy(next(case["value"] for case in CASES if case["name"] == name))


SCOPE = ContextScope(
    user_id=UUID("11111111-1111-4111-8111-111111111111"),
    session_id=UUID("22222222-2222-4222-8222-222222222222"),
)
TURN = UUID("33333333-3333-4333-8333-333333333333")
REQUEST = ConversationRequest(filtered_message="Which option?")


class HistoryHTTP:
    def __init__(self):
        self.requests = []
        self.capabilities = example("baseline")
        self.generation_headers = [
            ("X-SecondContext-Contract", "conversation-history-1"),
            ("X-SecondContext-Session", str(SCOPE.session_id)),
            ("X-SecondContext-Turn", str(TURN)),
            ("X-SecondContext-Snapshot", "0"),
        ]
        self.generation = {
            "id": "resp_synthetic",
            "object": "response",
            "status": "completed",
            "output_text": "The second one.",
            "metadata": {
                "session_id": str(SCOPE.session_id),
                "context_packet": {"user_external_id": self.capabilities["user"]},
            },
        }
        self.receipt = example("generated_receipt")

    def __call__(self, request):
        self.requests.append(request)
        if request.url.path.endswith("/v1/context/capabilities"):
            return httpx.Response(200, json=self.capabilities)
        if request.url.path.endswith("/v1/responses"):
            return httpx.Response(200, json=self.generation, headers=self.generation_headers)
        assert request.url.path.endswith("/v1/context/turns/finalize")
        return httpx.Response(200, json=self.receipt)


def provider(handler, namespace="oria", token="synthetic-secret", **kwargs):
    return SecondContextProvider(
        Settings(
            _env_file=None,
            second_context_base_url="http://context.invalid/prefix",
            second_context_subject_namespace=namespace,
            second_context_bearer_token=token,
        ),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_dtos_match_public_conformance_cases(case):
    adapters = {
        "CapabilitiesRequest": TypeAdapter(HistoryCapabilitiesRequest),
        "Capabilities": TypeAdapter(HistoryCapabilities),
        "FinalizeRequest": FINALIZE_REQUEST,
        "Receipt": RECEIPT,
    }
    adapter = adapters[case["definition"]]
    if case["valid"]:
        result = adapter.validate_json(json.dumps(case["value"]))
        assert result.model_dump(mode="json") == case["value"]
        assert validator(case["definition"]).is_valid(result.model_dump(mode="json"))
        assert "Which option" not in repr(result)
    else:
        with pytest.raises(ValidationError):
            adapter.validate_json(json.dumps(case["value"]))


async def test_prepared_turn_headers_body_and_pending_draft_are_exact_and_retriable():
    http = HistoryHTTP()
    client = provider(http)
    try:
        clock = datetime(2026, 11, 9, 12, tzinfo=UTC)
        prepared = client.prepare_history_turn(
            SCOPE,
            ConversationRequest(filtered_message="Which option?", reference_time_utc=clock),
            turn_id=TURN,
        )
        restored = PreparedHistoryTurn.model_validate_json(prepared.model_dump_json())
        drafts = [await client.respond_history(SCOPE, item) for item in (prepared, restored)]
        assert drafts[0] == drafts[1]
        assert drafts[0].turn_id == TURN and drafts[0].snapshot_sequence == 0
        assert drafts[0].response_id == "resp_synthetic"
        assert not hasattr(drafts[0], "status")  # generation is not acceptance
        assert len(http.requests) == 3  # capability cache + two identical generations
        assert http.requests[1].content == http.requests[2].content
        for sent in http.requests:
            body = json.loads(sent.content)
            assert sent.headers["Authorization"] == "Bearer synthetic-secret"
            assert sent.headers["X-SecondContext-Subject"] == body["user"]
        sent = http.requests[1]
        assert sent.url.path == "/prefix/v1/responses"
        assert sent.headers["X-SecondContext-Session"] == str(SCOPE.session_id)
        assert sent.headers["X-SecondContext-Turn"] == str(TURN)
        assert sent.headers["X-SecondContext-History"] == "recent"
        assert sent.headers["X-SecondContext-Acceptance"] == "explicit"
        body = json.loads(sent.content)
        assert set(body) == {"model", "input", "user", "instructions", "stream", "metadata"}
        assert body["metadata"] == {
            "session_id": str(SCOPE.session_id),
            "session_title": "Oria conversation",
            "goal": "follow_up",
        }
        assert "2026-11-09T12:00:00+00:00" in body["instructions"]
        assert body["input"] == "Which option?"
        assert not body["stream"] and body["model"] == "context-agent-1"
        assert "Which option" not in str(prepared)
    finally:
        await client.aclose()


@pytest.mark.parametrize("name", ["generated", "local", "local_sources", "abandon"])
async def test_finalize_exact_receipt_without_new_capture_capability(name):
    http = HistoryHTTP()
    http.receipt = example("local_receipt" if name.startswith("local") else f"{name}_receipt")
    client = provider(http)
    request = FINALIZE_REQUEST.validate_python(example(name))
    try:
        first = await client.finalize_history(SCOPE, request)
        assert first == await client.finalize_history(SCOPE, request)
        assert first.model_dump(mode="json") == http.receipt
        assert len(http.requests) == 2
        assert http.requests[0].content == http.requests[1].content
        assert json.loads(http.requests[0].content) == example(name)
        assert http.requests[0].headers["X-SecondContext-Subject"] == request.user
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract_version", 2),
        ("contract_version", True),
        ("contract_version", 1.0),
        ("user", "oria:foreign"),
        ("implementation", "legacy"),
        ("status", "pending"),
        ("generation_endpoints", ["/v1/responses"]),
        ("managed_input", "messages"),
        ("acceptance_modes", ["generated"]),
        ("history_modes", ["off"]),
        ("history_modes", ["off", "recent", "recent"]),
        ("finalize_actions", ["accept_generated", "abandon"]),
        ("history_coverage", "messages"),
        ("extra", "synthetic-private"),
    ],
)
async def test_unsupported_capabilities_never_generate_or_fall_back(field, value):
    http = HistoryHTTP()
    http.capabilities[field] = value
    client = provider(http)
    try:
        with pytest.raises(HistoryUnsupported):
            await client.respond_history(
                SCOPE, client.prepare_history_turn(SCOPE, REQUEST, turn_id=TURN)
            )
        assert len(http.requests) == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("recent_exchanges", 0),
        ("recent_exchanges", 65),
        ("user_characters", 4095),
        ("assistant_characters", 8192),
        ("pending_ttl_seconds", 3600),
        ("prompt_input_tokens", 0),
        ("reserved_output_tokens", True),
        ("reserved_output_tokens", 9007199254740992),
    ],
)
async def test_capability_limits_are_required_exact_types_and_bounded(field, value):
    http = HistoryHTTP()
    http.capabilities["limits"][field] = value
    client = provider(http)
    try:
        with pytest.raises(HistoryUnsupported):
            await client.history_capabilities(SCOPE.user_id)
    finally:
        await client.aclose()


async def test_cache_is_scoped_bounded_expires_and_refresh_failure_invalidates(monkeypatch):
    http = HistoryHTTP()

    def handler(request):
        http.capabilities["user"] = json.loads(request.content)["user"]
        return http(request)

    client = provider(handler)
    now = [100.0]
    monkeypatch.setattr("oria_engine.context.second_context.monotonic", lambda: now[0])
    try:
        for _ in range(2):
            await client.history_capabilities(SCOPE.user_id)
        assert len(http.requests) == 1
        for _ in range(129):
            await client.history_capabilities(uuid4())
        assert len(client._history_capabilities) == 128
        await client.history_capabilities(SCOPE.user_id)
        count = len(http.requests)
        now[0] += 61
        await client.history_capabilities(SCOPE.user_id)
        assert len(http.requests) == count + 1
        http.capabilities["status"] = "disabled"
        with pytest.raises(HistoryUnsupported):
            await client.history_capabilities(SCOPE.user_id, refresh=True)
        with pytest.raises(HistoryUnsupported):
            await client.history_capabilities(SCOPE.user_id)
        assert len(http.requests) == count + 3
        client.clear_history_capabilities()
        assert not client._history_capabilities
    finally:
        await client.aclose()


@pytest.mark.parametrize("header", ["Contract", "Session", "Turn", "Snapshot"])
@pytest.mark.parametrize("kind", ["missing", "wrong", "duplicate", "comma", "whitespace"])
async def test_generation_header_validation(header, kind):
    http = HistoryHTTP()
    name = f"X-SecondContext-{header}"
    value = dict(http.generation_headers)[name]
    http.generation_headers = [(k, v) for k, v in http.generation_headers if k != name]
    if kind != "missing":
        replacement = {"wrong": "wrong", "comma": f"{value},{value}", "whitespace": f" {value}"}
        http.generation_headers.append((name, replacement.get(kind, value)))
    if kind == "duplicate":
        http.generation_headers.append((name.lower(), value))
    client = provider(http)
    try:
        with pytest.raises(ContextUnavailable):
            await client.respond_history(
                SCOPE, client.prepare_history_turn(SCOPE, REQUEST, turn_id=TURN)
            )
        assert len(http.requests) == 2 and not client._history_capabilities
    finally:
        await client.aclose()


@pytest.mark.parametrize("snapshot", ["-1", "+1", "1.0", "9007199254740992", "١", "1" * 100])
async def test_snapshot_bounds(snapshot):
    http = HistoryHTTP()
    http.generation_headers[-1] = (b"X-SecondContext-Snapshot", snapshot.encode("utf-8"))
    client = provider(http)
    try:
        with pytest.raises(ContextUnavailable):
            await client.respond_history(
                SCOPE, client.prepare_history_turn(SCOPE, REQUEST, turn_id=TURN)
            )
    finally:
        await client.aclose()


@pytest.mark.parametrize("field", ["session", "owner", "status", "blank", "response_id"])
async def test_managed_response_body_is_scoped_and_complete(field):
    http = HistoryHTTP()
    if field == "session":
        http.generation["metadata"]["session_id"] = str(uuid4())
    elif field == "owner":
        http.generation["metadata"]["context_packet"]["user_external_id"] = "foreign"
    elif field == "status":
        http.generation["status"] = "in_progress"
    elif field == "blank":
        http.generation["output_text"] = " \n"
    else:
        http.generation["id"] = " "
    client = provider(http)
    try:
        with pytest.raises(ContextUnavailable):
            await client.respond_history(
                SCOPE, client.prepare_history_turn(SCOPE, REQUEST, turn_id=TURN)
            )
    finally:
        await client.aclose()


@pytest.mark.parametrize("shape", ["direct", "nested", "both"])
async def test_managed_subject_echo_compatibility(shape):
    http = HistoryHTTP()
    metadata = http.generation["metadata"]
    if shape != "nested":
        metadata["user_external_id"] = http.capabilities["user"]
    if shape == "direct":
        del metadata["context_packet"]
    client = provider(http)
    try:
        draft = await client.respond_history(
            SCOPE, client.prepare_history_turn(SCOPE, REQUEST, turn_id=TURN)
        )
        assert draft.user == http.capabilities["user"]
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"user_external_id": None},
        {"user_external_id": "foreign"},
        {"user_external_id": 42},
        {"user_external_id": "oria:11111111-1111-4111-8111-111111111111", "context_packet": {}},
        {
            "user_external_id": "oria:11111111-1111-4111-8111-111111111111",
            "context_packet": {"user_external_id": "foreign"},
        },
        {
            "user_external_id": "foreign",
            "context_packet": {"user_external_id": "oria:11111111-1111-4111-8111-111111111111"},
        },
    ],
)
async def test_missing_invalid_or_conflicting_managed_subject_echoes_fail_closed(metadata):
    http = HistoryHTTP()
    http.generation["metadata"] = {"session_id": str(SCOPE.session_id), **metadata}
    client = provider(http)
    try:
        with pytest.raises(ContextUnavailable):
            await client.respond_history(
                SCOPE, client.prepare_history_turn(SCOPE, REQUEST, turn_id=TURN)
            )
    finally:
        await client.aclose()


async def test_additive_generation_body_and_case_insensitive_headers_with_current_sources():
    from oria_engine.knowledge.contracts import RecordRef

    http = HistoryHTTP()
    http.generation["future_field"] = "ignored"
    http.generation_headers = [(name.lower(), value) for name, value in http.generation_headers]
    http.generation_headers[-1] = ("x-secondcontext-snapshot", "9007199254740991")
    client = provider(http)
    source = example("local_sources")["knowledge_refs"][0]
    try:
        prepared = client.prepare_history_turn(
            SCOPE,
            ConversationRequest(
                filtered_message="Which event?", knowledge_refs=(RecordRef.model_validate(source),)
            ),
            turn_id=TURN,
        )
        draft = await client.respond_history(SCOPE, prepared)
        assert draft.snapshot_sequence == 9007199254740991
        assert json.loads(http.requests[-1].content)["knowledge_refs"] == [source]
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract_version", True),
        ("user", "foreign"),
        ("session_id", "foreign"),
        ("turn_id", str(uuid4())),
        ("turn_id", str(TURN).replace("33333333", "AAAAAAAA")),
        ("action", "accept_local"),
        ("status", "pending"),
        ("response_id", "resp_other"),
        ("sequence", 0),
        ("sequence", True),
        ("sequence", "1"),
        ("sequence", 1.0),
        ("sequence", 9007199254740992),
        ("history_coverage", "messages"),
        ("extra", "synthetic-private"),
    ],
)
async def test_receipt_mismatch_never_acknowledges(field, value):
    http = HistoryHTTP()
    http.receipt[field] = value
    client = provider(http)
    try:
        with pytest.raises(ContextUnavailable) as error:
            await client.finalize_history(
                SCOPE, FINALIZE_REQUEST.validate_python(example("generated"))
            )
        assert "synthetic-private" not in str(error.value)
        assert len(http.requests) == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize("field", ["owner", "session"])
async def test_scope_mismatch_rejected_before_http(field):
    http = HistoryHTTP()
    client = provider(http)
    wrong = ContextScope(
        user_id=uuid4() if field == "owner" else SCOPE.user_id,
        session_id=uuid4() if field == "session" else SCOPE.session_id,
    )
    try:
        with pytest.raises(ContextUnavailable):
            await client.respond_history(
                wrong, client.prepare_history_turn(SCOPE, REQUEST, turn_id=TURN)
            )
        with pytest.raises(ContextUnavailable):
            await client.finalize_history(
                wrong, FINALIZE_REQUEST.validate_python(example("generated"))
            )
        assert not http.requests
    finally:
        await client.aclose()


@pytest.mark.parametrize("code,status", HISTORY_ERROR_STATUS.items())
async def test_only_contract_error_codes_survive_and_no_http_error_is_retried(code, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, json={"error": {"code": code, "message": "synthetic-private"}}
        )

    client = provider(handler)
    try:
        with pytest.raises(HistoryFailure) as error:
            await client.finalize_history(
                SCOPE, FINALIZE_REQUEST.validate_python(example("generated"))
            )
        assert error.value.code == code and error.value.status == status
        assert error.value.retryable == (
            code in {"turn_pending", "turn_in_progress", "history_unavailable"}
        )
        assert "synthetic-private" not in str(error.value)
        assert "synthetic-private" not in repr(vars(error.value))
        assert len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize("status", [201, 302, 401, 403, 404, 500, 503])
async def test_old_or_unknown_endpoint_never_proves_capability(status):
    client = provider(lambda request: httpx.Response(status, json=example("baseline")))
    try:
        with pytest.raises(HistoryUnsupported):
            await client.history_capabilities(SCOPE.user_id)
    finally:
        await client.aclose()


@pytest.mark.parametrize("operation", ["capability", "finalize", "generate"])
@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b"not-json",
        b'{"user":"a","user":"b"}',
        rb'{"x":"\ud800"}',
        b'{"x":NaN}',
        b"x" * 262145,
    ],
)
async def test_malformed_private_bodies_fail_closed(operation, body):
    http = HistoryHTTP()

    def handler(request):
        if operation == "generate" and request.url.path.endswith("capabilities"):
            return http(request)
        return httpx.Response(200, content=body, headers=http.generation_headers)

    client = provider(handler)
    try:
        with pytest.raises(ContextUnavailable):
            if operation == "capability":
                await client.history_capabilities(SCOPE.user_id)
            elif operation == "finalize":
                await client.finalize_history(
                    SCOPE, FINALIZE_REQUEST.validate_python(example("generated"))
                )
            else:
                await client.respond_history(
                    SCOPE, client.prepare_history_turn(SCOPE, REQUEST, turn_id=TURN)
                )
    finally:
        await client.aclose()


async def test_legacy_calls_do_not_probe_capability_or_send_history_headers():
    http = HistoryHTTP()
    client = provider(http)
    try:
        await client.respond(SCOPE, REQUEST)
        assert len(http.requests) == 1
        assert all(
            "history" not in name and "turn" not in name for name in http.requests[0].headers
        )
    finally:
        await client.aclose()


async def test_subject_bound_auth_remains_supported_and_unauthenticated_history_fails():
    http = HistoryHTTP()
    http.capabilities["user"] = str(SCOPE.user_id)
    http.generation["metadata"]["context_packet"]["user_external_id"] = str(SCOPE.user_id)
    client = provider(http, namespace="")
    anonymous = provider(http, namespace="", token="")
    try:
        await client.respond_history(
            SCOPE, client.prepare_history_turn(SCOPE, REQUEST, turn_id=TURN)
        )
        assert all("X-SecondContext-Subject" not in request.headers for request in http.requests)
        with pytest.raises(HistoryUnsupported):
            await anonymous.respond_history(
                SCOPE, anonymous.prepare_history_turn(SCOPE, REQUEST, turn_id=TURN)
            )
        assert len(http.requests) == 2
    finally:
        await client.aclose()
        await anonymous.aclose()


async def test_deadline_cancellation_and_ambiguous_finalize_are_not_retried():
    calls = []

    async def wait(request):
        calls.append(request)
        await asyncio.sleep(10)

    client = provider(wait, timeout=0.01)
    request = FINALIZE_REQUEST.validate_python(example("generated"))
    try:
        with pytest.raises(ContextUnavailable):
            await client.finalize_history(SCOPE, request)
        assert len(calls) == 1
        task = asyncio.create_task(client.finalize_history(SCOPE, request))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "error_type", [httpx.ReadTimeout, httpx.WriteError, httpx.RemoteProtocolError]
)
async def test_transport_ambiguity_requires_durable_caller_retry(error_type):
    calls = []

    def fail(request):
        calls.append(request)
        raise error_type("synthetic-private", request=request)

    client = provider(fail)
    try:
        with pytest.raises(ContextUnavailable) as error:
            await client.finalize_history(
                SCOPE, FINALIZE_REQUEST.validate_python(example("generated"))
            )
        assert len(calls) == 1 and "synthetic-private" not in str(error.value)
    finally:
        await client.aclose()


async def test_connection_establishment_retries_exact_finalization():
    calls = []

    def fail_twice(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectError("synthetic-private", request=request)
        return httpx.Response(200, json=example("generated_receipt"))

    client = provider(fail_twice)
    try:
        await client.finalize_history(SCOPE, FINALIZE_REQUEST.validate_python(example("generated")))
        assert len(calls) == 3 and len({call.content for call in calls}) == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize("operation", ["capability", "finalize"])
async def test_context_endpoint_decoded_stream_limit_and_close(operation):
    class Chunks(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b" " * 16384
            yield b"synthetic-private"

        async def aclose(self):
            self.closed = True

    stream = Chunks()
    client = provider(lambda request: httpx.Response(200, stream=stream))
    try:
        with pytest.raises(ContextUnavailable) as error:
            if operation == "capability":
                await client.history_capabilities(SCOPE.user_id)
            else:
                await client.finalize_history(
                    SCOPE, FINALIZE_REQUEST.validate_python(example("generated"))
                )
        assert stream.closed and "synthetic-private" not in str(error.value)
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": "synthetic-private"}},
        {"error": {"code": "turn_conflict"}},  # known code with wrong status
        {"error": {"code": {"unexpected": "synthetic-private"}}},
    ],
)
async def test_unknown_or_wrong_status_error_codes_are_not_exposed(body):
    client = provider(lambda request: httpx.Response(503, json=body))
    try:
        with pytest.raises(ContextUnavailable) as error:
            await client.finalize_history(
                SCOPE, FINALIZE_REQUEST.validate_python(example("generated"))
            )
        assert not isinstance(error.value, HistoryFailure)
        assert "synthetic-private" not in str(error.value)
    finally:
        await client.aclose()


def test_local_sources_text_limits_and_unsupported_prepared_configuration():
    value = example("local_sources")
    value["user_text"] = "🌙" * 4096
    value["assistant_text"] = "🌙" * 16384
    assert AcceptLocal.model_validate(value)
    for replacement in (
        {"user_text": "x" * 4097},
        {"assistant_text": "x" * 16385},
        {"user_text": " \n"},
        {"assistant_text": "\ud800"},
        {"knowledge_refs": value["knowledge_refs"] * 2},
        {"knowledge_refs": [{**value["knowledge_refs"][0], "revision": 9007199254740992}]},
        {"metadata": {"raw_input": "synthetic-private"}},
    ):
        with pytest.raises(ValidationError):
            AcceptLocal.model_validate({**value, **replacement})
    prepared = {
        "contract_version": 1,
        "user": value["user"],
        "session_id": value["session_id"],
        "turn_id": value["turn_id"],
        "knowledge_refs": [],
        "input": "Hello",
        "instructions": "Current facts only",
        "goal": "follow_up",
    }
    for name, unsupported in (
        ("history", "adaptive"),
        ("acceptance", "generated"),
        ("metadata", {}),
    ):
        with pytest.raises(ValidationError):
            PreparedHistoryTurn.model_validate({**prepared, name: unsupported})
