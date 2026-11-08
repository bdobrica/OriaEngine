"""Synthetic natural-date examples and precision/authority regressions."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from oria_engine.domain.active import route_active
from oria_engine.domain.temporal import EventAnchor, analyze_temporal
from oria_engine.knowledge.contracts import CalendarDate, RecordRef
from oria_engine.privacy.messages import prepare_active_input

NOW = datetime(2026, 11, 8, 23, 30, tzinfo=UTC)  # November 9 in Berlin.


def analyze(text, zone="Europe/Berlin", now=NOW, anchors=()):
    return analyze_temporal(text, received_at=now, current_timezone=zone, anchors=anchors)


@pytest.mark.parametrize(
    "text,kind,expected",
    [
        ("in two hours", "instant", "2026-11-09T01:30:00Z"),
        ("today", "date", "2026-11-09"),
        ("tomorrow", "date", "2026-11-10"),
        ("this day last year", "date", "2025-11-09"),
        ("exactly nine months ago", "date", "2026-02-09"),
        ("May 1st, 2020", "date", "2020-05-01"),
        ("May 1st, last year", "date", "2025-05-01"),
        ("1 May 2020", "date", "2020-05-01"),
        ("Sep 2nd, 2020", "date", "2020-09-02"),
        ("we married this day last year at 3pm", "instant", "2025-11-09T14:00:00Z"),
    ],
)
def test_design_examples_resolve_without_model_clock(text, kind, expected):
    result = analyze(text).mentions
    assert len(result) == 1
    assert result[0].issue is None
    value = result[0].evidence.value
    assert value.kind == kind
    assert value.model_dump(mode="json")["value"] == expected
    assert result[0].evidence.reference_time_utc == NOW
    assert result == analyze(text).mentions  # retries cannot change the reference


@pytest.mark.parametrize(
    "text,role",
    [
        ("I was born May 1st, 2020", "birth_input"),
        ("My girlfriend was born 1992-06-14", "birth_input"),
        ("My girlfriend was ｂｏｒｎ 1992-06-14", "birth_input"),
        ("My girlfriend was bo\u200brn 1992-06-14", "birth_input"),
        ("Change my birth date to 1992-06-14", "profile_correction"),
        ("Our wedding day was May 1st, 2020", "life_event"),
        ("I bought my house May 1st, last year", "life_event"),
        ("I got the cat exactly nine months ago", "life_event"),
        ("I changed my job this day last year", "life_event"),
        ("I founded my business 2020-05-01", "life_event"),
        ("My parents got divorced yesterday", "life_event"),
        ("transits on May 1st, last year", "target"),
    ],
)
def test_roles_do_not_authorize_profile_edits_or_transits(text, role):
    assert analyze(text).mentions[0].role == role
    if role != "target":
        assert (
            route_active(text, received_at=NOW, current_timezone="Europe/Berlin").kind
            == "follow_up"
        )


def test_multiple_entities_dates_and_goals_remain_separate():
    text = "We married May 1st, 2020 and my girlfriend was born June 2nd, 1990; transits tomorrow"
    mentions = analyze(text).mentions
    assert [m.role for m in mentions] == ["life_event", "birth_input", "target"]
    assert [m.evidence.value.value for m in mentions] == [
        date(2020, 5, 1),
        date(1990, 6, 2),
        date(2026, 11, 10),
    ]
    route = route_active(text, received_at=NOW, current_timezone="Europe/Berlin")
    assert route.target_timestamp_utc == datetime(2026, 11, 10, 11, tzinfo=UTC)
    prepared = prepare_active_input(text)
    assert "June" not in prepared and "1990" not in prepared
    assert "We married May 1st, 2020" in prepared and "transits tomorrow" in prepared
    assert prepare_active_input(prepared) == prepared


def test_multiple_event_clocks_do_not_become_ambiguous_tool_targets():
    text = "We married 2020-05-01 at 3pm and we adopted our cat 2021-05-02 at 4pm"
    mentions = analyze(text).mentions
    assert len(mentions) == 2 and all(m.issue is None for m in mentions)
    assert route_active(text, received_at=NOW, current_timezone="Europe/Berlin").kind == "follow_up"
    for ambiguous in ("transits tomorrow at 3pm or at 4pm", "transits May 1st, 2020 or at 4pm"):
        assert (
            route_active(ambiguous, received_at=NOW, current_timezone="Europe/Berlin").kind
            == "clarify_date"
        )


def test_date_only_partial_approximate_and_unknown_clock_do_not_invent_noon():
    result = analyze("I got the cat around May 2020").mentions[0].evidence.value
    assert result.kind == "partial_date" and result.year == 2020 and result.month == 5
    assert result.day is None and result.approximate
    assert analyze("we married 1700-05-01", zone=None).mentions[0].evidence.value == CalendarDate(
        value=date(1700, 5, 1)
    )
    local = analyze("we married May 1st, 2020 at 3pm", zone=None).mentions[0]
    assert local.evidence.value.kind == "local_datetime"
    assert local.evidence.value.value == datetime(2020, 5, 1, 15)
    assert local.issue is None
    assert analyze("May 1st", zone=None).mentions[0].evidence.value.year is None


def test_timezone_provenance_and_explicit_event_override():
    event = analyze("we married this day last year at 3pm UTC").mentions[0]
    assert event.evidence.timezone_source == "explicit_event"
    assert event.evidence.value.value == datetime(2025, 11, 8, 15, tzinfo=UTC)
    assert analyze("we married yesterday", zone=None).mentions[0].issue == "timezone"
    assert analyze("we married 2020-05-01 at 3pm EST").mentions[0].issue == "timezone"
    assert analyze("we married 2020-05-01 at 3pm Europe/Imaginary").mentions[0].issue == "timezone"


@pytest.mark.parametrize("day", ["2026-03-29", "2026-10-25"])
def test_dst_event_clock_never_chooses_a_fold_or_gap(day):
    assert analyze(f"We married {day} at 02:30").mentions[0].issue == "clock"


def test_explicit_transit_requests_preserve_legacy_day_part_sampling():
    assert route_active(
        "transits today at noon", received_at=NOW, current_timezone="Europe/Berlin"
    ).target_timestamp_utc == datetime(2026, 11, 9, 11, tzinfo=UTC)
    assert route_active(
        "transits tomorrow morning", received_at=NOW, current_timezone="Europe/Berlin"
    ).target_timestamp_utc == datetime(2026, 11, 10, 8, tzinfo=UTC)
    event = analyze("We married May 1st, 2020 at noon", zone=None).mentions[0]
    assert event.evidence.value.value == datetime(2020, 5, 1, 12)


def test_calendar_clamp_and_elapsed_dst_rules_are_distinct():
    now = datetime(2028, 11, 30, 12, tzinfo=UTC)
    assert analyze("exactly nine months ago", now=now).mentions[0].evidence.value.value == date(
        2028, 2, 29
    )
    assert analyze("this day last year", now=datetime(2028, 2, 29, tzinfo=UTC)).mentions[
        0
    ].evidence.value.value == date(2027, 2, 28)
    now = datetime(2026, 3, 28, 12, tzinfo=UTC)
    assert analyze("in 24 hours", now=now).mentions[0].evidence.value.value == datetime(
        2026, 3, 29, 12, tzinfo=UTC
    )
    assert analyze("in one day", now=now).mentions[0].evidence.value.value == date(2026, 3, 29)


def test_anniversary_and_historical_anchor_have_distinct_years_and_provenance():
    ref = RecordRef(kind="event", id=uuid4(), revision=3)
    birthday = EventAnchor(
        label="my birthday", day=date(1992, 6, 14), recurring=True, reference=ref
    )
    historical = EventAnchor(label="the day I was born", day=date(1992, 6, 14), reference=ref)
    assert analyze("a week before my birthday").mentions[0].issue == "anchor"
    assert analyze("a week before my birthday", anchors=(birthday,)).mentions[0].issue == "year"
    mention = analyze("a week before my birthday next year", anchors=(birthday,)).mentions[0]
    assert mention.evidence.value.value == date(2027, 6, 7) and mention.evidence.anchor == ref
    assert analyze("the day I was born", anchors=(historical,)).mentions[
        0
    ].evidence.value.value == date(1992, 6, 14)
    # Two matching local labels are ambiguous; never select an account by label.
    assert (
        analyze("my birthday next year", anchors=(birthday, birthday)).mentions[0].issue == "anchor"
    )


def test_leap_anniversary_requires_observance_and_keeps_original_date():
    leap = EventAnchor(label="my birthday", day=date(2000, 2, 29), recurring=True)
    assert (
        analyze("a week before my birthday next year", anchors=(leap,)).mentions[0].issue
        == "leap_day"
    )
    assert leap.day == date(2000, 2, 29)
    observed = leap.model_copy(update={"leap_day_observance": "march_1"})
    assert analyze("a week before my birthday next year", anchors=(observed,)).mentions[
        0
    ].evidence.value.value == date(2027, 2, 22)
    assert observed.day == leap.day


def test_arbitrary_application_supplied_event_anchor_preserves_revision():
    ref = RecordRef(kind="event", id=uuid4(), revision=2)
    launch = EventAnchor(label="the launch", day=date(2020, 5, 1), reference=ref)
    mention = analyze("a week before the launch", anchors=(launch,)).mentions[0]
    assert mention.evidence.value.value == date(2020, 4, 24)
    assert mention.evidence.anchor == ref and mention.role == "anniversary"


@pytest.mark.parametrize(
    "text",
    [
        "May I ask about my chart?",
        "I feel anxious today",
        "I met her yesterday",
        "Imagine we married tomorrow",
        "Can we go on a date?",
    ],
)
def test_ordinary_narrative_or_modal_words_do_not_become_transits(text):
    assert route_active(text, received_at=NOW, current_timezone="Europe/Berlin").kind in {
        "follow_up",
        "natal_explanation",
    }


def test_same_message_anchor_and_ranges_do_not_invent_calculations():
    result = analyze("We married 2020-05-01; a week after our wedding day")
    assert result.mentions[1].evidence.value.value == date(2020, 5, 8)
    assert result.mentions[1].role == "anniversary"
    result = analyze("We travelled between May 1st, 2020 and May 3rd, 2020")
    assert result.mentions[0].evidence.value.kind == "interval"
    assert analyze("between 2020-05-03 and 2020-05-01").mentions[0].issue == "date"
    assert (
        route_active("transits between May 1st, 2020 and May 3rd, 2020", received_at=NOW).kind
        == "clarify_date"
    )


@pytest.mark.parametrize("text", ["2026-01-01 at 15:30", "2026-01-01 at 5pm"])
def test_absolute_clock_requests_need_zone_and_then_resolve(text):
    assert route_active(text, received_at=NOW).kind == "clarify_timezone"
    assert route_active(text, received_at=NOW, current_timezone="UTC").kind == "transits_for_date"


@pytest.mark.parametrize("text", ["04/05/2026", "May 40th, 2020", "February 29, 2025"])
def test_ambiguous_or_impossible_dates_remain_unresolved(text):
    assert analyze(text).mentions[0].issue == "date"


@pytest.mark.parametrize(
    "text",
    [
        "She was ｂｏｒｎ in Exampletown. 1992-06-14 at 12:30.",
        "Her birth date follows. 1992-06-14.",
    ],
)
def test_birth_continuations_never_authorize_a_transit(text):
    assert analyze(text).narrative
    assert route_active(text, received_at=NOW, current_timezone="UTC").kind == "follow_up"
