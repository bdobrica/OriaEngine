from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from astrology_mcp.engine import calculate, calculate_transits
from pydantic import ValidationError

from oria_engine.astrology.contracts import NatalRequest
from oria_engine.domain.active import ActiveIntent, prepare_active, render_active, route_active

NOW = datetime(2026, 9, 28, 19, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Explain my natal chart", "natal_explanation"),
        ("What does my moon mean?", "natal_explanation"),
        ("Explain my Cancer moon", "natal_explanation"),
        ("What are my transits today?", "current_transits"),
        ("transits", "current_transits"),
        ("transits on 2026-10-02", "transits_for_date"),
        ("2026-10-02", "transits_for_date"),
        ("What does that mean?", "follow_up"),
        ("Will I get cancer today?", "unsupported_high_stakes"),
        ("Will my stocks rise on 2026-10-02?", "unsupported_high_stakes"),
    ],
)
def test_routes(text, kind):
    result = route_active(text, received_at=NOW)
    assert result.kind == kind
    if kind == "current_transits":
        assert result.target_timestamp_utc == NOW
    elif kind == "transits_for_date":
        assert result.target_timestamp_utc == datetime(2026, 10, 2, 12, tzinfo=UTC)
    else:
        assert result.target_timestamp_utc is None


@pytest.mark.parametrize(
    "text",
    [
        "transits on 04/05/2026",
        "transits tomorrow",
        "next Friday",
        "May 2",
        "2026-02-30",
        "2026-02-01 or 2026-02-02",
        "today or 2026-02-01",
        "1799-01-01",
        "2400-01-01",
        "2026-01-01 at 15:30",
        "2026-1-2",
        "transits next month",
        "2026-01-01T12:00:00Z",
        "2026-01-01 at 5pm",
        "transits for the 5th",
        "transits next spring",
        "transits this evening",
    ],
)
def test_ambiguous_or_unsupported_dates(text):
    assert route_active(text, received_at=NOW).kind == "clarify_date"


def test_intent_invariants():
    with pytest.raises(ValidationError):
        ActiveIntent(kind="transits_for_date")
    with pytest.raises(ValidationError):
        ActiveIntent(kind="natal_explanation", target_timestamp_utc=NOW)


@pytest.mark.parametrize("accuracy", ["exact", "approximate", "unknown"])
async def test_minimal_facts_and_rendering(accuracy):
    natal = calculate(
        NatalRequest(
            birth_time_accuracy=accuracy,
            latitude=51.5,
            longitude=0,
            timestamp_utc=None if accuracy == "unknown" else datetime(2000, 1, 1, 12, tzinfo=UTC),
            local_birth_date="2000-01-01" if accuracy == "unknown" else None,
        )
    )
    client = AsyncMock()
    client.calculate_transits.side_effect = calculate_transits
    for text in ("natal chart", "what does that mean?", "tomorrow", "medical advice"):
        facts = await prepare_active(text, received_at=NOW, natal=natal, client=client)
        assert facts.transits is None
        assert (facts.natal is not None) == (text == "natal chart")
        assert render_active(facts)
    client.calculate_transits.assert_not_called()
    client.calculate_natal_chart.assert_not_called()
    facts = await prepare_active("today", received_at=NOW, natal=natal, client=client)
    assert facts.natal is None and facts.transits is not None
    assert facts.transits.target_timestamp_utc == NOW
    output = render_active(facts)
    assert "2026-09-28 19:30:00 UTC" in output
    assert "time-to-exact are unavailable" in output
    assert len(output) < 4096
    if accuracy == "unknown":
        assert "not personalized" in output and not facts.transits.aspects
    if accuracy == "approximate":
        assert "approximate" in output
