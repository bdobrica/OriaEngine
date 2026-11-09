"""SecondContext HTTP boundary. Never log bodies, headers, URLs or exception inputs."""

import asyncio
import re
from collections import OrderedDict
from time import monotonic
from typing import Any, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from oria_engine.config import Settings
from oria_engine.context.contracts import (
    MEMORY_TEXT,
    ContextReply,
    ContextScope,
    ContextUnavailable,
    ConversationRequest,
    MemoryKind,
)
from oria_engine.context.history import (
    HISTORY_ERROR_STATUS,
    MAX_SEQUENCE,
    RECEIPT,
    FinalizeRequest,
    HistoryCapabilities,
    HistoryCapabilitiesRequest,
    HistoryDraft,
    HistoryFailure,
    HistoryIdentity,
    HistoryRecordRef,
    HistoryUnsupported,
    PreparedHistoryTurn,
    Receipt,
    parse_history_json,
    validate_history_receipt,
)
from oria_engine.knowledge.contracts import (
    ProjectionCapabilities,
    ProjectionDelete,
    ProjectionMatches,
    ProjectionQuery,
    ProjectionReceipt,
    ProjectionUpsert,
    validate_matches,
    validate_receipt,
)
from oria_engine.observability import observed
from oria_engine.persona.prompts import build_instructions


class _ResponseMetadata(BaseModel):
    session_id: UUID
    context_packet: dict[str, Any] = Field(default_factory=dict)


class _Response(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    id: str = Field(min_length=1, max_length=256)
    object: Literal["response"]
    status: Literal["completed"]
    output_text: str = Field(min_length=1, max_length=16384)
    metadata: _ResponseMetadata


class _Memory(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    id: UUID
    user_id: UUID
    summary: str
    source: Literal["oria"]


class _Purge(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    contract_version: Literal[1]
    user: str
    status: Literal["completed"]


class SecondContextProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 20,
    ) -> None:
        self.knowledge_enabled = settings.second_context_knowledge_enabled
        self.timeout = timeout
        self.namespace = settings.second_context_subject_namespace
        token = settings.second_context_bearer_token.get_secret_value()
        self._history_authenticated = bool(token)
        # Readiness is scoped, bounded, and never survives this provider/configuration epoch.
        self._history_capabilities: OrderedDict[str, tuple[float, HistoryCapabilities]] = (
            OrderedDict()
        )
        self._client = httpx.AsyncClient(
            base_url=settings.second_context_base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=httpx.Timeout(timeout, connect=min(3, timeout)),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def subject(self, user_id: UUID) -> str:
        return f"{self.namespace}:{user_id}" if self.namespace else str(user_id)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, payload: dict[str, Any]) -> bytes:
        data, _ = await self._exchange(path, payload)
        return data

    async def _exchange(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        history: bool = False,
        history_headers: dict[str, str] | None = None,
        response_limit: int = 262144,
    ) -> tuple[bytes, httpx.Headers]:
        try:
            async with asyncio.timeout(self.timeout):
                for attempt in range(3):
                    try:
                        headers = (
                            {"X-SecondContext-Subject": payload["user"]} if self.namespace else {}
                        )
                        headers.update(history_headers or {})
                        async with self._client.stream(
                            "POST", path, json=payload, headers=headers
                        ) as response:
                            if not history and not 200 <= response.status_code < 300:
                                raise ContextUnavailable()
                            data = bytearray()
                            async for chunk in response.aiter_bytes():
                                if len(data) + len(chunk) > response_limit:
                                    raise ContextUnavailable()
                                data.extend(chunk)
                            if history and response.status_code != 200:
                                self._history_error(response.status_code, bytes(data))
                            return bytes(data), response.headers
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        # No request was sent. Legacy writes lack idempotency keys;
                        # ambiguous managed writes belong to durable caller recovery.
                        if attempt == 2:
                            raise
                        await asyncio.sleep(0.1 * 2**attempt)
        except HistoryFailure:
            raise
        except (httpx.HTTPError, TimeoutError, ContextUnavailable):
            raise ContextUnavailable("Conversation context temporarily unavailable") from None
        raise ContextUnavailable("Conversation context temporarily unavailable")

    @staticmethod
    def _history_error(status: int, data: bytes) -> None:
        try:
            body = parse_history_json(data)
            code = body["error"]["code"]
            if isinstance(code, str) and HISTORY_ERROR_STATUS.get(code) == status:
                raise HistoryFailure(
                    status,
                    code,
                    retryable=code in {"turn_in_progress", "turn_pending", "history_unavailable"},
                )
        except (ValueError, KeyError, TypeError, RecursionError):
            pass
        raise ContextUnavailable("Conversation history request failed")

    def _require_history_auth(self) -> None:
        if not self._history_authenticated:
            raise HistoryUnsupported("Conversation history requires authenticated storage")

    def clear_history_capabilities(self) -> None:
        """Call after a provider deployment change; readiness is never durable authority."""
        self._history_capabilities.clear()

    async def history_capabilities(
        self, user_id: UUID, *, refresh: bool = False
    ) -> HistoryCapabilities:
        self._require_history_auth()
        subject = self.subject(user_id)
        cached = self._history_capabilities.pop(subject, None)
        if not refresh and cached is not None and cached[0] > monotonic():
            self._history_capabilities[subject] = cached
            return cached[1]
        try:
            payload = HistoryCapabilitiesRequest(user=subject).model_dump(mode="json")
            data, _ = await self._exchange(
                "v1/context/capabilities", payload, history=True, response_limit=16384
            )
            result = HistoryCapabilities.model_validate(parse_history_json(data))
            if result.user != subject:
                raise ValueError()
        except (ContextUnavailable, ValueError, RecursionError):
            raise HistoryUnsupported("Conversation history capability unavailable") from None
        self._history_capabilities[subject] = (monotonic() + 60, result)
        while len(self._history_capabilities) > 128:
            self._history_capabilities.popitem(last=False)
        return result

    def prepare_history_turn(
        self, scope: ContextScope, request: ConversationRequest, *, turn_id: UUID
    ) -> PreparedHistoryTurn:
        """Pure preparation; caller must persist encrypted input before respond_history."""
        return PreparedHistoryTurn(
            contract_version=1,
            user=self.subject(scope.user_id),
            session_id=str(scope.session_id),
            turn_id=turn_id,
            input=request.filtered_message,
            instructions=build_instructions(
                natal_facts=request.natal_facts,
                transit_facts=request.transit_facts,
                linked_facts=request.linked_facts,
                reference_time_utc=request.reference_time_utc,
            ),
            goal=request.goal,
            knowledge_refs=tuple(
                HistoryRecordRef.model_validate(ref.model_dump()) for ref in request.knowledge_refs
            ),
        )

    def _history_scope(self, scope: ContextScope, request: HistoryIdentity) -> None:
        self._require_history_auth()
        if request.user != self.subject(scope.user_id) or request.session_id != str(
            scope.session_id
        ):
            raise ContextUnavailable("Conversation history scope mismatch")

    @observed("second_context_respond")
    async def respond_history(
        self, scope: ContextScope, request: PreparedHistoryTurn
    ) -> HistoryDraft:
        self._history_scope(scope, request)
        await self.history_capabilities(scope.user_id)
        headers = {
            "X-SecondContext-Session": request.session_id,
            "X-SecondContext-History": "recent",
            "X-SecondContext-Turn": str(request.turn_id),
            "X-SecondContext-Acceptance": "explicit",
        }
        try:
            data, echoes = await self._exchange(
                "v1/responses", request.response_body(), history=True, history_headers=headers
            )
            for name, expected in (
                ("X-SecondContext-Contract", "conversation-history-1"),
                ("X-SecondContext-Session", request.session_id),
                ("X-SecondContext-Turn", str(request.turn_id)),
            ):
                if echoes.get_list(name) != [expected]:
                    raise ValueError()
            snapshots = echoes.get_list("X-SecondContext-Snapshot")
            if len(snapshots) != 1 or re.fullmatch(r"[0-9]{1,16}", snapshots[0]) is None:
                raise ValueError()
            snapshot = int(snapshots[0])
            if snapshot > MAX_SEQUENCE:
                raise ValueError()
            body = parse_history_json(data)
            result = _Response.model_validate(body)
            if body["metadata"]["session_id"] != request.session_id:
                raise ValueError()
            if result.metadata.context_packet.get("user_external_id") != request.user:
                raise ValueError()
            return HistoryDraft(
                contract_version=1,
                user=request.user,
                session_id=request.session_id,
                turn_id=request.turn_id,
                response_id=result.id,
                text=result.output_text,
                snapshot_sequence=snapshot,
            )
        except ContextUnavailable:
            self._history_capabilities.pop(request.user, None)
            raise
        except (ValueError, KeyError, TypeError, RecursionError):
            self._history_capabilities.pop(request.user, None)
            raise ContextUnavailable("Invalid conversation history response") from None

    async def finalize_history(self, scope: ContextScope, request: FinalizeRequest) -> Receipt:
        """Post-commit recovery lane, also usable when new history capture is disabled.

        OCH3 owns consent, source checks, local eligibility and durable retry payloads.
        This method never infers local acceptance eligibility from a valid DTO.
        """
        self._history_scope(scope, request)
        try:
            payload = request.model_dump(mode="json")
            if len(httpx.Request("POST", "http://context.invalid", json=payload).content) > 131072:
                raise ValueError()
            data, _ = await self._exchange(
                "v1/context/turns/finalize", payload, history=True, response_limit=16384
            )
            receipt = RECEIPT.validate_python(parse_history_json(data))
            validate_history_receipt(request, receipt)
            return receipt
        except ContextUnavailable:
            self._history_capabilities.pop(request.user, None)
            raise
        except (ValueError, RecursionError):
            self._history_capabilities.pop(request.user, None)
            raise ContextUnavailable("Invalid conversation history acknowledgement") from None

    @observed("second_context_respond")
    async def respond(self, scope: ContextScope, request: ConversationRequest) -> ContextReply:
        payload = {
            "model": "context-agent-1",
            "user": self.subject(scope.user_id),
            "input": request.filtered_message,
            "instructions": build_instructions(
                natal_facts=request.natal_facts,
                transit_facts=request.transit_facts,
                linked_facts=request.linked_facts,
                reference_time_utc=request.reference_time_utc,
            ),
            "stream": False,
            "metadata": {
                "session_id": str(scope.session_id),
                "session_title": "Oria conversation",
                "goal": request.goal,
            },
        }
        if request.knowledge_refs:
            payload["knowledge_refs"] = [
                ref.model_dump(mode="json") for ref in request.knowledge_refs
            ]
        data = await self._post("v1/responses", payload)
        try:
            result = _Response.model_validate_json(data)
            if result.metadata.session_id != scope.session_id:
                raise ValueError()
            if result.metadata.context_packet.get("user_external_id") != self.subject(
                scope.user_id
            ):
                raise ValueError()
            return ContextReply(response_id=result.id, text=result.output_text)
        except (ValidationError, ValueError):
            raise ContextUnavailable("Invalid conversation context response") from None

    @observed("second_context_remember")
    async def remember(self, scope: ContextScope, kind: MemoryKind) -> None:
        # Only fixed application-owned phrases may enter semantic memory. There is
        # deliberately no raw_text parameter or arbitrary metadata escape hatch.
        if kind not in MEMORY_TEXT:
            raise ValueError("Unsupported conversational memory")
        phrase = MEMORY_TEXT[kind]
        data = await self._post(
            "memory/ingest",
            {
                "user": self.subject(scope.user_id),
                "raw_text": phrase,
                "summary": phrase,
                "type": "preference"
                if kind in ("concise_readings", "less_mystical_language", "explicit_uncertainty")
                else "conversation_topic",
                "source": "oria",
                "metadata": {"session_id": str(scope.session_id)},
            },
        )
        try:
            result = _Memory.model_validate_json(data)
            if result.summary != phrase:
                raise ValueError()
        except (ValidationError, ValueError):
            raise ContextUnavailable("Invalid conversational memory response") from None

    @observed("second_context_purge")
    async def purge(self, user_id: UUID) -> None:
        subject = self.subject(user_id)
        data = await self._post("v1/subjects/purge", {"user": subject})
        try:
            result = _Purge.model_validate_json(data)
            if result.user != subject:
                raise ValueError()
        except (ValidationError, ValueError):
            raise ContextUnavailable("Invalid subject purge response") from None

    async def projection_capabilities(self, user_id: UUID) -> None:
        data = await self._post("v1/knowledge/capabilities", {"user": self.subject(user_id)})

        try:
            result = ProjectionCapabilities.model_validate_json(data)
            if result.user != self.subject(user_id):
                raise ValueError()
        except ValueError:
            raise ContextUnavailable("Linked context capability unavailable") from None

    async def project(self, request: ProjectionUpsert | ProjectionDelete) -> None:
        data = await self._post(
            f"v1/knowledge/{request.operation}", request.model_dump(mode="json")
        )
        try:
            validate_receipt(request, ProjectionReceipt.model_validate_json(data))
        except ValueError:
            raise ContextUnavailable("Invalid projection acknowledgement") from None

    async def query_projections(self, request: ProjectionQuery) -> ProjectionMatches:
        data = await self._post("v1/knowledge/query", request.model_dump(mode="json"))
        try:
            result = ProjectionMatches.model_validate_json(data)
            validate_matches(request, result)
            return result
        except ValueError:
            raise ContextUnavailable("Invalid linked context response") from None
