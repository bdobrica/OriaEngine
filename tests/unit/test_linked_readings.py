"""Input precision, traditional themes and local interpretation, using synthetic facts."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from astrology_mcp.linked import calculate_synastry

from oria_engine.astrology.linked import ChartInput, SynastryRequest
from oria_engine.domain.projections import safe_text, themes
from oria_engine.domain.readings import (
    LinkedReading,
    ReadingChart,
    ReadingComparison,
    event_input,
    interpretation_summary,
    render_linked,
    requested_rating,
    wants_linked,
)
from oria_engine.knowledge.contracts import CalendarDate, EventRecord, Instant, TemporalEvidence
from oria_engine.persona.houses import HOUSE_REFERENCE
from oria_engine.persona.prompts import build_instructions


def event(value, *, zone=None, source="unknown", place=None):
    return EventRecord(
        id=uuid4(),
        revision=1,
        event_type="birth",
        description="synthetic",
        place=place,
        source_message_id=uuid4(),
        temporal=TemporalEvidence(
            expression="synthetic",
            reference_time_utc=datetime(2026, 11, 8, tzinfo=UTC),
            timezone=zone,
            timezone_source=source,
            value=value,
            resolution_version="test",
        ),
    )


async def test_date_only_does_not_need_place_or_timezone():
    resolver = AsyncMock()
    result = await event_input(event(CalendarDate(value="1992-06-02")), resolver)
    assert result.accuracy == "unknown" and result.timestamp_utc is None
    assert result.latitude is None
    resolver.resolve.assert_not_called()


async def test_current_timezone_is_not_a_historical_birth_timezone():
    resolver = AsyncMock()
    value = Instant(value="1992-06-01T22:30:00Z")
    current = await event_input(
        event(value, zone="Europe/Berlin", source="current_preference"), resolver
    )
    assert str(current.calendar_date) == "1992-06-02" and current.timestamp_utc is None
    explicit = await event_input(
        event(value, zone="Europe/Berlin", source="explicit_event"), resolver
    )
    assert explicit.timestamp_utc == value.value and explicit.accuracy == "exact"
    assert explicit.latitude is None


@pytest.mark.parametrize("house", range(1, 13))
def test_all_twelve_topics_and_explicit_house_requests_are_available(house):
    assert themes(f"house {house}") == (house,)
    assert themes(f"{house}th house") == (house,)
    assert f"{house} " in HOUSE_REFERENCE


def facts():
    result = calculate_synastry(
        SynastryRequest(
            calculation_id=uuid4(),
            chart_a=ChartInput(accuracy="unknown", calendar_date="1990-04-13"),
            chart_b=ChartInput(accuracy="unknown", calendar_date="1992-06-02"),
        )
    )
    comparison = ReadingComparison(
        a="self", b="other", aspects=result.aspects, overlays=result.overlays
    )
    return LinkedReading(
        kind="compatibility",
        charts=(
            ReadingChart(role="self", facts=result.chart_a),
            ReadingChart(role="other", facts=result.chart_b),
        ),
        comparisons=(comparison,),
        rating=requested_rating("Rate our compatibility", [comparison]),
    )


def test_rating_is_requested_interpretation_with_current_facts():
    reading = facts()
    assert reading.rating is not None and 1 <= reading.rating.score <= 10
    assert requested_rating("Tell me about our relationship", list(reading.comparisons)) is None
    assert requested_rating("Rate us", []) is None
    text = render_linked(reading)
    assert "/10" in text and "sample" in text
    assert safe_text(interpretation_summary(reading))
    instructions = build_instructions(linked_facts=reading)
    assert HOUSE_REFERENCE in instructions
    assert "1992-06-02" not in instructions and "1990-04-13" not in instructions
    assert "Calculated linked facts" in instructions
    assert wants_linked("Rate my compatibility with my girlfriend")
    assert wants_linked("Interpret our wedding chart")
    assert not wants_linked("We married May 1st, 2020")
    assert not wants_linked("Interpret my natal chart")
    assert not wants_linked("We married May 1st, 2020. Tell me about my chart.")
