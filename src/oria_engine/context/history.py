"""Closed conversation-history-1 DTOs; shape validation never grants consent/authority."""

import json
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BeforeValidator, Field, TypeAdapter, field_validator, model_validator

from oria_engine.astrology.contracts import WireModel
from oria_engine.context.contracts import ContextUnavailable
from oria_engine.knowledge.contracts import RecordRef

MAX_SEQUENCE = 9007199254740991
PositiveSequence = Annotated[int, Field(strict=True, ge=1, le=MAX_SEQUENCE)]
Subject = Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")]
SessionID = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]
ResponseID = Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")]
UserText = Annotated[str, Field(min_length=1, max_length=4096, pattern=r"\S")]
AssistantText = Annotated[str, Field(min_length=1, max_length=16384, pattern=r"\S")]


def _canonical_uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        parsed = UUID(value)
        if str(parsed) == value:
            return parsed
    raise ValueError("Expected canonical UUID")


CanonicalUUID = Annotated[UUID, BeforeValidator(_canonical_uuid)]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("Invalid JSON number")


def parse_history_json(data: bytes) -> Any:
    """Reject ambiguous JSON and invalid Unicode, including in ignored response fields."""
    value = json.loads(
        data.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant
    )
    json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return value


class HistoryModel(WireModel):
    @field_validator(
        "contract_version",
        "user_characters",
        "assistant_characters",
        "pending_ttl_seconds",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def exact_constants(cls, value: object) -> object:
        # Literal[int] otherwise accepts True and integral floats in Pydantic.
        if isinstance(value, (bool, float)):
            raise ValueError("Expected exact wire type")
        return value

    @field_validator("*")
    @classmethod
    def valid_unicode(cls, value: Any) -> Any:
        if isinstance(value, str):
            value.encode("utf-8")
        return value


class HistoryCapabilitiesRequest(HistoryModel):
    user: Subject


class HistoryLimits(HistoryModel):
    recent_exchanges: int = Field(strict=True, ge=1, le=64)
    user_characters: Literal[4096]
    assistant_characters: Literal[16384]
    prompt_input_tokens: PositiveSequence
    reserved_output_tokens: PositiveSequence
    pending_ttl_seconds: Literal[86400]


class HistoryCapabilities(HistoryCapabilitiesRequest):
    contract_version: Literal[1]
    implementation: Literal["conversation-history-1"]
    status: Literal["ready"]
    generation_endpoints: tuple[Literal["/v1/responses", "/v1/chat/completions"], ...]
    managed_input: Literal["single_user_text"]
    acceptance_modes: tuple[Literal["generated", "explicit"], ...]
    history_modes: tuple[Literal["off", "recent", "adaptive"], ...]
    finalize_actions: tuple[Literal["accept_generated", "accept_local", "abandon"], ...]
    history_coverage: Literal["linked_sessions"]
    limits: HistoryLimits

    @model_validator(mode="after")
    def supported_profile(self) -> Self:
        for values, required in (
            (self.generation_endpoints, {"/v1/responses", "/v1/chat/completions"}),
            (self.acceptance_modes, {"generated", "explicit"}),
            (self.history_modes, {"off", "recent"}),
            (self.finalize_actions, {"accept_generated", "accept_local", "abandon"}),
        ):
            if len(values) != len(set(values)) or not required.issubset(values):
                raise ValueError("Unsupported history profile")
        return self


class HistoryIdentity(HistoryModel):
    contract_version: Literal[1]
    user: Subject
    session_id: SessionID
    turn_id: CanonicalUUID


class HistoryRecordRef(RecordRef):
    id: CanonicalUUID
    revision: PositiveSequence


class HistorySources(HistoryModel):
    knowledge_refs: tuple[HistoryRecordRef, ...] = Field(max_length=20)

    @field_validator("knowledge_refs")
    @classmethod
    def unique_refs(cls, value: tuple[HistoryRecordRef, ...]) -> tuple[HistoryRecordRef, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Duplicate source reference")
        return value


class AcceptGenerated(HistoryIdentity):
    action: Literal["accept_generated"]
    response_id: ResponseID
    assistant_text: AssistantText


class AcceptLocal(HistoryIdentity, HistorySources):
    action: Literal["accept_local"]
    user_text: UserText
    assistant_text: AssistantText


class Abandon(HistoryIdentity):
    action: Literal["abandon"]


FinalizeRequest = Annotated[AcceptGenerated | AcceptLocal | Abandon, Field(discriminator="action")]
FINALIZE_REQUEST: TypeAdapter[FinalizeRequest] = TypeAdapter(FinalizeRequest)


class HistoryReceipt(HistoryIdentity):
    sequence: PositiveSequence
    history_coverage: Literal["linked_sessions"]


class GeneratedReceipt(HistoryReceipt):
    action: Literal["accept_generated"]
    status: Literal["accepted"]
    response_id: ResponseID


class LocalReceipt(HistoryReceipt):
    action: Literal["accept_local"]
    status: Literal["accepted"]


class AbandonReceipt(HistoryReceipt):
    action: Literal["abandon"]
    status: Literal["abandoned"]


Receipt = Annotated[GeneratedReceipt | LocalReceipt | AbandonReceipt, Field(discriminator="action")]
RECEIPT: TypeAdapter[Receipt] = TypeAdapter(Receipt)


def validate_history_receipt(request: FinalizeRequest, receipt: Receipt) -> None:
    for field in ("user", "session_id", "turn_id", "action"):
        if getattr(request, field) != getattr(receipt, field):
            raise ValueError("History receipt mismatch")
    if isinstance(request, AcceptGenerated) and (
        not isinstance(receipt, GeneratedReceipt) or request.response_id != receipt.response_id
    ):
        raise ValueError("History response mismatch")


class PreparedHistoryTurn(HistoryIdentity, HistorySources):
    """Freeze after preparation; OCH3 must encrypt/persist this before the first attempt.

    Fixed recent/explicit Responses profile. No arbitrary metadata or raw envelope.
    The caller supplies the persisted ingress UUID; the adapter never allocates one.
    """

    input: UserText
    instructions: str
    goal: Literal["natal_explanation", "current_transits", "transits_for_date", "follow_up"]

    def response_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": "context-agent-1",
            "user": self.user,
            "input": self.input,
            "instructions": self.instructions,
            "stream": False,
            "metadata": {
                "session_id": self.session_id,
                "session_title": "Oria conversation",
                "goal": self.goal,
            },
        }
        if self.knowledge_refs:
            body["knowledge_refs"] = [ref.model_dump(mode="json") for ref in self.knowledge_refs]
        return body


class HistoryDraft(HistoryIdentity):
    response_id: ResponseID
    text: AssistantText
    snapshot_sequence: int = Field(strict=True, ge=0, le=MAX_SEQUENCE)


class HistoryUnsupported(ContextUnavailable):
    """Unsupported credentials, capability or profile; never downgrade to legacy."""


class HistoryFailure(ContextUnavailable):
    """Only allowlisted code/status are exposed; never retain upstream error text."""

    def __init__(self, status: int, code: str, *, retryable: bool) -> None:
        super().__init__("Conversation history request failed")
        self.status = status
        self.code = code
        self.retryable = retryable


HISTORY_ERROR_STATUS = {
    "invalid_history_request": 400,
    "session_conflict": 400,
    "unsupported_feature": 400,
    "unsupported_history_input": 400,
    "context_budget_exceeded": 400,
    "turn_not_found": 404,
    "session_not_found": 404,
    "turn_in_progress": 409,
    "turn_pending": 409,
    "turn_conflict": 409,
    "turn_abandoned": 409,
    "history_source_conflict": 409,
    "turn_expired": 410,
    "session_deleted": 410,
    "subject_deleted": 410,
    "history_unavailable": 503,
}
