"""Projection contents are bounded data and topics never imply measured placements."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from oria_engine.config import Settings
from oria_engine.db.knowledge import SavedRecord
from oria_engine.domain.projections import canonical_projection, safe_text, themes
from oria_engine.knowledge.contracts import EntityRecord, EventRecord


@pytest.mark.parametrize(
    ("text", "house"),
    [
        ("identity", 1),
        ("self-worth", 2),
        ("siblings", 3),
        ("home", 4),
        ("creativity", 5),
        ("pets and routines", 6),
        ("relationships", 7),
        ("shared resources", 8),
        ("philosophy", 9),
        ("career", 10),
        ("networks", 11),
        ("dreams and endings", 12),
    ],
)
def test_all_traditional_themes_available(text, house):
    assert house in themes(text)
    assert not themes("unrelated example")


@pytest.mark.parametrize(
    "text",
    [
        "Birthday is June second",
        "1992-06-02",
        "12:34",
        "password: synthetic-secret",
        "She was born in spring",
    ],
)
def test_raw_birth_dates_and_credentials_not_interpretation_memories(text):
    assert not safe_text(text)


def test_canonical_projection_omits_raw_event_context_and_sensitive_labels():
    event = EventRecord(
        id=uuid4(),
        revision=1,
        event_type="birth",
        description="Someone was born June 2nd in Privateplace",
        place="Privateplace",
        source_message_id=uuid4(),
    )
    result = canonical_projection(SavedRecord(event))
    assert "June" not in result.model_dump_json() and "Privateplace" not in result.model_dump_json()
    entity = EntityRecord(
        id=uuid4(),
        revision=1,
        entity_type="person",
        label="born 1992",
        aliases=("do not project aliases",),
        source_message_id=uuid4(),
    )
    result = canonical_projection(SavedRecord(entity))
    assert result.label == "person" and "aliases" not in result.model_dump_json()


def test_linked_context_requires_explicit_scoped_service_configuration():
    assert not Settings(_env_file=None).second_context_knowledge_enabled
    with pytest.raises(ValidationError):
        Settings(_env_file=None, second_context_knowledge_enabled=True)
