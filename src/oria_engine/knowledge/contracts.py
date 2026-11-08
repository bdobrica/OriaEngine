"""Versioned knowledge DTOs; schemas are never authorization.

Canonical payloads stay in Oria. Only explicit projection DTOs may cross the scoped
SecondContext boundary. Subject/owner selection always comes from authenticated code.
"""

from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, Field, TypeAdapter, field_validator, model_validator

from oria_engine.astrology.contracts import WireModel

Version = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")]
Revision = Annotated[int, Field(strict=True, ge=1)]
Label = Annotated[str, Field(min_length=1, max_length=160)]
House = Annotated[int, Field(strict=True, ge=1, le=12)]
Subject = Annotated[
    str,
    Field(pattern=r"^(?:[a-z][a-z0-9_-]{0,31}:)?[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"),
]


def _utc(value: datetime) -> datetime:
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("Expected an aware UTC instant")
    return value


UTCInstant = Annotated[datetime, AfterValidator(_utc)]


class RecordRef(WireModel):
    kind: Literal["entity", "event", "reading"]
    id: UUID
    revision: Revision


class CalendarDate(WireModel):
    kind: Literal["date"] = "date"
    value: date
    approximate: bool = False


class Instant(WireModel):
    kind: Literal["instant"] = "instant"
    value: UTCInstant
    approximate: bool = False


class LocalDateTime(WireModel):
    kind: Literal["local_datetime"] = "local_datetime"
    value: datetime
    approximate: bool = False

    @field_validator("value", mode="before")
    @classmethod
    def explicit_clock(cls, value: object) -> object:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and len(value) > 10 and value[10] in {"T", "t", " "}:
            return value
        raise ValueError("Local datetime requires an explicitly supplied clock")

    @model_validator(mode="after")
    def naive(self) -> Self:
        if self.value.tzinfo is not None:
            raise ValueError("Local clock must not imply a known UTC offset")
        return self


class PartialDate(WireModel):
    kind: Literal["partial_date"] = "partial_date"
    year: int | None = Field(default=None, ge=1, le=9999)
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    approximate: bool = False

    @model_validator(mode="after")
    def possible_date(self) -> Self:
        if self.year is None and self.month is None and self.day is None:
            raise ValueError("Partial date needs at least one component")
        if self.year is not None and self.month is not None and self.day is not None:
            raise ValueError("Complete dates use the date variant")
        if self.day is not None and self.month is not None:
            # 2000 admits February 29 when the year is unknown.
            date(self.year or 2000, self.month, self.day)
        return self


class DateInterval(WireModel):
    kind: Literal["interval"] = "interval"
    start: CalendarDate | Instant
    end: CalendarDate | Instant

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if type(self.start) is not type(self.end):
            raise ValueError("Interval endpoints need the same precision")
        if self.start.value > self.end.value:
            raise ValueError("Interval endpoints are reversed")
        return self


class Anniversary(WireModel):
    kind: Literal["anniversary"] = "anniversary"
    anchor: RecordRef
    occurrence_year: int | None = Field(default=None, ge=1, le=9999)
    leap_day_observance: Literal["february_28", "march_1", "february_29_only"] | None = None

    @model_validator(mode="after")
    def event_anchor(self) -> Self:
        if self.anchor.kind != "event":
            raise ValueError("An anniversary references an event")
        return self


TemporalValue = Annotated[
    CalendarDate | Instant | LocalDateTime | PartialDate | DateInterval | Anniversary,
    Field(discriminator="kind"),
]


class TemporalEvidence(WireModel):
    expression: str = Field(min_length=1, max_length=4096)
    reference_time_utc: UTCInstant
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    timezone_source: Literal["explicit_event", "current_preference", "unknown"] = "unknown"
    anchor: RecordRef | None = None
    resolution_version: Version
    value: TemporalValue | None = None

    @model_validator(mode="after")
    def timezone_provenance(self) -> Self:
        if (self.timezone is None) != (self.timezone_source == "unknown"):
            raise ValueError("Timezone and its provenance must agree")
        return self


class EntityRecord(WireModel):
    contract_version: Literal[1] = 1
    kind: Literal["entity"] = "entity"
    id: UUID
    revision: Revision
    entity_type: Literal["person", "pet", "organization", "possession", "other"]
    label: Label
    aliases: tuple[Label, ...] = Field(default=(), max_length=20)
    relationship_to_user: Label | None = None
    source_message_id: UUID


class Participant(WireModel):
    entity_id: UUID
    role: Label


class EventRecord(WireModel):
    contract_version: Literal[1] = 1
    kind: Literal["event"] = "event"
    id: UUID
    revision: Revision
    event_type: Label
    description: str = Field(min_length=1, max_length=4096)
    participants: tuple[Participant, ...] = Field(default=(), max_length=32)
    temporal: TemporalEvidence | None = None
    place: Label | None = None
    source_message_id: UUID
    # Own-birth events refer to the existing canonical profile, not duplicate inputs.
    natal_profile_revision: Revision | None = None


class Salience(WireModel):
    score: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)
    basis: Literal["user_stated", "inferred"]
    method_version: Version


class ContextProjection(WireModel):
    record: RecordRef
    label: Label
    summary: str = Field(min_length=1, max_length=2048)
    knowledge_kind: Literal["user_statement", "interpretation"]
    sources: tuple[RecordRef, ...] = Field(min_length=1, max_length=32)
    house_themes: tuple[House, ...] = Field(default=(), max_length=12)
    salience: Salience | None = None

    @model_validator(mode="after")
    def unique_houses(self) -> Self:
        if len(set(self.house_themes)) != len(self.house_themes):
            raise ValueError("House themes must be unique")
        return self


class ProjectionCapabilitiesRequest(WireModel):
    user: Subject


class ProjectionCapabilities(WireModel):
    contract_version: Literal[1] = 1
    user: Subject
    implementation: Literal["linked-context-1"]
    history_coverage: Literal["linked_sessions"]
    index: Literal["postgres"]
    status: Literal["ready"]


class ProjectionUpsert(WireModel):
    contract_version: Literal[1] = 1
    operation: Literal["upsert"] = "upsert"
    user: Subject
    operation_id: UUID
    projection: ContextProjection


class ProjectionDelete(WireModel):
    contract_version: Literal[1] = 1
    operation: Literal["delete"] = "delete"
    user: Subject
    operation_id: UUID
    record: RecordRef


class ProjectionQuery(WireModel):
    contract_version: Literal[1] = 1
    operation: Literal["query"] = "query"
    user: Subject
    references: tuple[RecordRef, ...] = Field(default=(), max_length=32)
    house_themes: tuple[House, ...] = Field(default=(), max_length=12)
    limit: int = Field(default=10, ge=1, le=20)

    @model_validator(mode="after")
    def bounded_selection(self) -> Self:
        if not self.references and not self.house_themes:
            raise ValueError("Query needs scoped record links or house themes")
        return self


class ProjectionReceipt(WireModel):
    contract_version: Literal[1] = 1
    operation: Literal["upsert", "delete"]
    user: Subject
    operation_id: UUID
    record: RecordRef
    status: Literal["completed"]
    coverage: Literal["projection_and_indexes", "active_stores_and_linked_history"]

    @model_validator(mode="after")
    def complete_erasure(self) -> Self:
        expected = (
            "active_stores_and_linked_history"
            if self.operation == "delete"
            else "projection_and_indexes"
        )
        if self.coverage != expected:
            raise ValueError("Operation requires its complete declared coverage")
        return self


class ProjectionMatches(WireModel):
    contract_version: Literal[1] = 1
    operation: Literal["query"] = "query"
    user: Subject
    matches: tuple[ContextProjection, ...] = Field(max_length=20)


def validate_receipt(
    request: ProjectionUpsert | ProjectionDelete, receipt: ProjectionReceipt
) -> None:
    record = request.projection.record if isinstance(request, ProjectionUpsert) else request.record
    if (
        receipt.user != request.user
        or receipt.operation_id != request.operation_id
        or receipt.operation != request.operation
        or receipt.record != record
    ):
        raise ValueError("Projection acknowledgement does not match the requested operation")


def validate_matches(request: ProjectionQuery, response: ProjectionMatches) -> None:
    if response.user != request.user or len(response.matches) > request.limit:
        raise ValueError("Projection results do not match the scoped bounded request")


CanonicalRecord = Annotated[EntityRecord | EventRecord, Field(discriminator="kind")]
ProjectionRequest = Annotated[
    ProjectionUpsert | ProjectionDelete | ProjectionQuery, Field(discriminator="operation")
]


def schema_document() -> dict[str, object]:
    return {
        "status": "v1; optional linked-context-1 service capability required",
        "capabilities_request": ProjectionCapabilitiesRequest.model_json_schema(),
        "capabilities": ProjectionCapabilities.model_json_schema(),
        "canonical": TypeAdapter(CanonicalRecord).json_schema(),
        "projection_request": TypeAdapter(ProjectionRequest).json_schema(),
        "projection_receipt": ProjectionReceipt.model_json_schema(),
        "projection_matches": ProjectionMatches.model_json_schema(),
    }
