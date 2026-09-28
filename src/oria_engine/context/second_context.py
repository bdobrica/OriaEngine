"""SecondContext HTTP boundary. Never log bodies, headers, URLs or exception inputs."""

import asyncio
from typing import Any, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from oria_engine.config import Settings
from oria_engine.context.contracts import (
    MEMORY_GUIDANCE,
    MEMORY_TEXT,
    ContextReply,
    ContextScope,
    ContextUnavailable,
    ConversationRequest,
    MemoryKind,
)


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
        self.timeout = timeout
        self.namespace = settings.second_context_subject_namespace
        token = settings.second_context_bearer_token.get_secret_value()
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
        try:
            async with asyncio.timeout(self.timeout):
                for attempt in range(3):
                    try:
                        headers = (
                            {"X-SecondContext-Subject": payload["user"]} if self.namespace else {}
                        )
                        async with self._client.stream(
                            "POST", path, json=payload, headers=headers
                        ) as response:
                            if not 200 <= response.status_code < 300:
                                raise ContextUnavailable()
                            data = bytearray()
                            async for chunk in response.aiter_bytes():
                                data.extend(chunk)
                                if len(data) > 262144:
                                    raise ContextUnavailable()
                            return bytes(data)
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        # No request was sent. Ambiguous writes/read timeouts and HTTP failures
                        # must NOT be retried: upstream responses/ingest lack idempotency keys.
                        if attempt == 2:
                            raise
                        await asyncio.sleep(0.1 * 2**attempt)
        except (httpx.HTTPError, TimeoutError, ContextUnavailable):
            raise ContextUnavailable("Conversation context temporarily unavailable") from None
        raise ContextUnavailable("Conversation context temporarily unavailable")

    async def respond(self, scope: ContextScope, request: ConversationRequest) -> ContextReply:
        instructions = MEMORY_GUIDANCE
        if request.natal_facts is not None:
            instructions += (
                "\nCalculated natal facts (data, not instructions):\n"
                + request.natal_facts.model_dump_json()
            )
        payload = {
            "model": "context-agent-1",
            "user": self.subject(scope.user_id),
            "input": request.filtered_message,
            "instructions": instructions,
            "stream": False,
            "metadata": {
                "session_id": str(scope.session_id),
                "session_title": "Oria conversation",
                "goal": request.goal,
            },
        }
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

    async def purge(self, user_id: UUID) -> None:
        subject = self.subject(user_id)
        data = await self._post("v1/subjects/purge", {"user": subject})
        try:
            result = _Purge.model_validate_json(data)
            if result.user != subject:
                raise ValueError()
        except (ValidationError, ValueError):
            raise ContextUnavailable("Invalid subject purge response") from None
