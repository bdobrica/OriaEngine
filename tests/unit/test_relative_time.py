from datetime import UTC, datetime

import pytest

from oria_engine.domain.active import route_active

# 01:30 Friday in Bucharest, while it is still Thursday UTC.
NOW = datetime(2026, 10, 29, 23, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "text,target",
    [
        ("So how's my day going to be tomorrow at work?", "2026-10-31T10:00:00+00:00"),
        ("yesterday", "2026-10-29T10:00:00+00:00"),
        ("day after tomorrow", "2026-11-01T10:00:00+00:00"),
        ("in 3 hours", "2026-10-30T02:30:00+00:00"),
        ("in three hours", "2026-10-30T02:30:00+00:00"),
        ("two hours ago", "2026-10-29T21:30:00+00:00"),
        ("30 minutes from now", "2026-10-30T00:00:00+00:00"),
        ("in 1 day", "2026-10-30T23:30:00+00:00"),
        ("in 2 weeks", "2026-11-12T23:30:00+00:00"),
        ("next month", "2026-11-29T23:30:00+00:00"),
        ("next year", "2027-10-29T22:30:00+00:00"),
        ("next Friday", "2026-11-06T10:00:00+00:00"),
        ("last Friday", "2026-10-23T09:00:00+00:00"),
        ("this Friday", "2026-10-30T10:00:00+00:00"),
        ("tomorrow at 15:30", "2026-10-31T13:30:00+00:00"),
        ("tomorrow at 5pm", "2026-10-31T15:00:00+00:00"),
        ("tomorrow morning", "2026-10-31T07:00:00+00:00"),
        ("this afternoon", "2026-10-30T13:00:00+00:00"),
        ("tonight", "2026-10-30T19:00:00+00:00"),
        ("today at noon", "2026-10-30T10:00:00+00:00"),
    ],
)
def test_relative_targets_use_explicit_local_zone(text, target):
    result = route_active(text, received_at=NOW, current_timezone="Europe/Bucharest")
    assert result.kind == "transits_for_date"
    assert result.target_timestamp_utc == datetime.fromisoformat(target)


@pytest.mark.parametrize("text", ["in 3 hours", "three hours from now", "in 40 minutes"])
def test_elapsed_offsets_do_not_require_a_timezone(text):
    assert route_active(text, received_at=NOW).target_timestamp_utc is not None


@pytest.mark.parametrize(
    "text",
    [
        "tomorrow or Friday",
        "tomorrow and yesterday",
        "in 3 hours tomorrow",
        "transits in two hours tonight",
        "tomorrow at 25:00",
        "tomorrow at 5",
        "in 100000 years",
        "in -3 hours",
        "in 1.5 hours",
        "tomorrow at 3pm or at 4pm",
        "this week",
        "next spring",
        "tomorrow 2026-11-01",
        "in 2 weeks and 3 days",
        "3 hours",
        "tomorrow next week",
    ],
)
def test_unsupported_or_ambiguous_targets_never_guess(text):
    assert (
        route_active(text, received_at=NOW, current_timezone="Europe/Bucharest").kind
        == "clarify_date"
    )


@pytest.mark.parametrize("now", ["2026-03-28T12:00:00+00:00", "2026-10-24T12:00:00+00:00"])
def test_nonexistent_and_repeated_local_times_require_clarification(now):
    # Bucharest 03:30 either does not exist or occurs twice on these dates.
    result = route_active(
        "tomorrow at 03:30",
        received_at=datetime.fromisoformat(now),
        current_timezone="Europe/Bucharest",
    )
    assert result.kind == "clarify_date"


def test_calendar_day_differs_from_elapsed_24_hours_at_dst():
    now = datetime(2026, 3, 28, 10, tzinfo=UTC)
    calendar = route_active("in 1 day", received_at=now, current_timezone="Europe/Bucharest")
    elapsed = route_active("in 24 hours", received_at=now, current_timezone="Europe/Bucharest")
    assert calendar.target_timestamp_utc == datetime(2026, 3, 29, 9, tzinfo=UTC)
    assert elapsed.target_timestamp_utc == datetime(2026, 3, 29, 10, tzinfo=UTC)


def test_month_end_clamps_and_legacy_iso_noon_remains_compatible():
    now = datetime(2028, 1, 31, 10, tzinfo=UTC)
    assert route_active(
        "next month", received_at=now, current_timezone="UTC"
    ).target_timestamp_utc == datetime(2028, 2, 29, 10, tzinfo=UTC)
    assert route_active(
        "2026-11-01", received_at=NOW, current_timezone="Europe/Bucharest"
    ).target_timestamp_utc == datetime(2026, 11, 1, 12, tzinfo=UTC)


def test_career_follow_up_and_high_stakes_priority():
    assert route_active("Yup, do career, please!", received_at=NOW).kind == "follow_up"
    assert (
        route_active("How can I hurt my partner tomorrow?", received_at=NOW).kind
        == "unsupported_high_stakes"
    )
