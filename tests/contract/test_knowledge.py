"""Candidate contract invariants; no claim that a remote service implements them."""

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from oria_engine.knowledge.contracts import (
    Anniversary,
    CalendarDate,
    ContextProjection,
    DateInterval,
    EntityRecord,
    EventRecord,
    Instant,
    LocalDateTime,
    PartialDate,
    ProjectionDelete,
    ProjectionMatches,
    ProjectionQuery,
    ProjectionReceipt,
    ProjectionUpsert,
    RecordRef,
    Salience,
    TemporalEvidence,
    schema_document,
    validate_matches,
    validate_receipt,
)

ROOT = Path(__file__).resolve().parents[2]
SUBJECT = "oria:11111111-1111-4111-8111-111111111111"


def reference():
    return RecordRef(kind="event", id=uuid4(), revision=1)


def projection():
    ref = reference()
    return ContextProjection(
        record=ref,
        label="Our wedding",
        summary="The user describes the wedding as important.",
        knowledge_kind="user_statement",
        sources=(ref,),
        house_themes=(4, 7, 8),
        salience=Salience(score=0.9, basis="user_stated", method_version="explicit-1"),
    )


def test_generated_schema_matches_source_and_check_command():
    assert json.loads((ROOT / "contracts/knowledge/v1.json").read_text()) == schema_document()
    subprocess.run(
        [sys.executable, "scripts/generate_knowledge_schema.py", "--check"], cwd=ROOT, check=True
    )


@pytest.mark.parametrize(
    "value",
    [
        CalendarDate(value=date(2020, 5, 1)),
        Instant(value=datetime(2020, 5, 1, 12, tzinfo=UTC)),
        LocalDateTime(value=datetime(2020, 5, 1, 15)),
        PartialDate(year=2020),
        PartialDate(month=2, day=29),
        DateInterval(
            start=CalendarDate(value=date(2020, 5, 1)), end=CalendarDate(value=date(2020, 5, 2))
        ),
        Anniversary(anchor=reference()),
    ],
)
def test_temporal_precision_and_reference_clock_survive_round_trip(value):
    evidence = TemporalEvidence(
        expression="this day last year",
        reference_time_utc=datetime(2021, 5, 1, 9, tzinfo=UTC),
        resolution_version="calendar-1",
        value=value,
    )
    assert TemporalEvidence.model_validate_json(evidence.model_dump_json()) == evidence
    if isinstance(value, CalendarDate):
        assert evidence.value.value == date(2020, 5, 1)
        assert "T12:" not in evidence.model_dump_json()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Instant(value=datetime(2020, 5, 1)),
        lambda: LocalDateTime(value=datetime(2020, 5, 1, tzinfo=UTC)),
        lambda: LocalDateTime(value="2020-05-01"),
        lambda: LocalDateTime(value=date(2020, 5, 1)),
        lambda: PartialDate(),
        lambda: PartialDate(month=2, day=30),
        lambda: PartialDate(year=2020, month=5, day=1),
        lambda: DateInterval(
            start=CalendarDate(value=date(2020, 5, 2)), end=CalendarDate(value=date(2020, 5, 1))
        ),
        lambda: DateInterval(
            start=CalendarDate(value=date(2020, 5, 1)),
            end=Instant(value=datetime(2020, 5, 2, tzinfo=UTC)),
        ),
        lambda: Anniversary(anchor=RecordRef(kind="entity", id=uuid4(), revision=1)),
        lambda: RecordRef(kind="event", id=uuid4(), revision=True),
        lambda: Salience(score=float("nan"), basis="inferred", method_version="rules-1"),
        lambda: TemporalEvidence(
            expression="today",
            reference_time_utc=datetime.now(UTC),
            resolution_version="calendar-1",
            timezone="UTC",
        ),
    ],
)
def test_impossible_or_ambiguous_typed_values_are_rejected(factory):
    with pytest.raises(ValidationError):
        factory()


@pytest.mark.parametrize("kind", ["person", "pet", "organization", "possession", "other"])
def test_entity_payload_is_closed_redacted_and_has_no_model_selected_owner(kind):
    record = EntityRecord(
        id=uuid4(),
        revision=1,
        entity_type=kind,
        label="Synthetic entity",
        source_message_id=uuid4(),
    )
    assert "Synthetic entity" not in repr(record)
    with pytest.raises(ValidationError):
        EntityRecord.model_validate({**record.model_dump(), "owner_id": str(uuid4())})
    assert not {"birth_date", "latitude", "password"} & set(type(record).model_fields)


def test_event_accepts_an_unknown_date():
    event = EventRecord(
        id=uuid4(),
        revision=1,
        event_type="wedding",
        description="Our wedding",
        source_message_id=uuid4(),
    )
    assert event.temporal is None
    assert EventRecord.model_validate_json(event.model_dump_json()) == event


@pytest.mark.parametrize(
    "field,value",
    [("birth_date", "1990-04-13"), ("raw_text", "profile"), ("metadata", {"owner": "another"})],
)
def test_projection_cannot_add_raw_profile_or_metadata_fields(field, value):
    with pytest.raises(ValidationError):
        ContextProjection.model_validate({**projection().model_dump(), field: value})


def test_projection_references_and_house_themes_are_explicit_not_placements():
    current = projection()
    for bad in [(0,), (13,), (7, 7)]:
        with pytest.raises(ValidationError):
            ContextProjection.model_validate({**current.model_dump(), "house_themes": bad})
    with pytest.raises(ValidationError):
        ContextProjection.model_validate({**current.model_dump(), "sources": []})
    with pytest.raises(ValidationError):
        ContextProjection.model_validate(
            {**current.model_dump(), "knowledge_kind": "calculated_fact"}
        )


def test_receipts_require_exact_subject_operation_and_record_revision():
    request = ProjectionUpsert(user=SUBJECT, operation_id=uuid4(), projection=projection())
    receipt = ProjectionReceipt(
        operation="upsert",
        user=SUBJECT,
        operation_id=request.operation_id,
        record=request.projection.record,
        status="completed",
        coverage="projection_and_indexes",
    )
    validate_receipt(request, receipt)
    for change in [
        {"user": str(uuid4())},
        {"operation_id": uuid4()},
        {"operation": "delete"},
        {"record": request.projection.record.model_copy(update={"revision": 2})},
    ]:
        with pytest.raises(ValueError):
            validate_receipt(request, receipt.model_copy(update=change))


def test_selective_delete_cannot_acknowledge_only_index_hiding():
    request = ProjectionDelete(user=SUBJECT, operation_id=uuid4(), record=reference())
    body = dict(
        operation="delete",
        user=SUBJECT,
        operation_id=request.operation_id,
        record=request.record,
        status="completed",
    )
    with pytest.raises(ValidationError):
        ProjectionReceipt(**body, coverage="projection_and_indexes")
    validate_receipt(
        request, ProjectionReceipt(**body, coverage="active_stores_and_linked_history")
    )


def test_retrieval_is_scoped_and_bounded_without_an_unfiltered_profile_query():
    with pytest.raises(ValidationError):
        ProjectionQuery(user=SUBJECT)
    request = ProjectionQuery(user=SUBJECT, references=(reference(),), limit=1)
    validate_matches(request, ProjectionMatches(user=SUBJECT, matches=(projection(),)))
    for response in [
        ProjectionMatches(user=str(uuid4()), matches=()),
        ProjectionMatches(user=SUBJECT, matches=(projection(), projection())),
    ]:
        with pytest.raises(ValueError):
            validate_matches(request, response)
