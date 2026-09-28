import gzip
import hashlib
import json
from datetime import UTC, date, datetime, time
from importlib.resources import files
from uuid import uuid4

import pytest
from pydantic import ValidationError

from oria_engine.domain.birth_profile import BirthProfilePayload
from oria_engine.domain.birth_time import birth_zone, resolve_utc, utc_candidates
from oria_engine.domain.consent import OnboardingState as State
from oria_engine.domain.onboarding import reply_for, resolve_state
from oria_engine.domain.onboarding_data import OnboardingDraft
from oria_engine.domain.places import LocalPlaceResolver, TooManyPlaces


@pytest.fixture(scope="module")
def resolver():
    return LocalPlaceResolver()


@pytest.mark.parametrize(
    ("city", "country", "timezone", "latitude", "longitude"),
    [
        ("București", "Romania", "Europe/Bucharest", 44.43, 26.11),
        ("New York City", "US", "America/New_York", 40.71, -74.01),
        ("Kathmandu", "Nepal", "Asia/Kathmandu", 27.70, 85.32),
        ("Sydney", "Australia", "Australia/Sydney", -33.87, 151.21),
    ],
)
async def test_local_cities(resolver, city, country, timezone, latitude, longitude):
    candidates = await resolver.resolve(city, country)
    assert len(candidates) == 1
    place = candidates[0]
    assert place.timezone == timezone
    assert place.latitude == pytest.approx(latitude, abs=0.02)
    assert place.longitude == pytest.approx(longitude, abs=0.02)


async def test_aliases_country_scope_and_missing_city(resolver):
    expected = await resolver.resolve("Bucharest", "RO")
    assert expected == await resolver.resolve("  bucuresti ", "rou")
    assert await resolver.resolve("Bucharest", "United States") == ()
    assert await resolver.resolve("No Such Synthetic Town", "RO") == ()
    assert await resolver.resolve("Bucharest", "invented country") == ()


async def test_ambiguity_never_selects_or_hides_a_place(resolver):
    # The full snapshot has more than eight Springfields; a region narrows lookup.
    with pytest.raises(TooManyPlaces):
        await resolver.resolve("Springfield", "US")
    places = await resolver.resolve("Springfield - Illinois", "United States")
    assert len(places) == 1 and places[0].region == "Illinois"
    # Force a bounded ambiguity using real, validated fixtures in a separate instance.
    local = LocalPlaceResolver()
    ids = sorted(local.index[("US", "springfield")])[:2]
    local.index[("US", "synthetic alias")] = set(ids)
    assert await local.resolve("synthetic alias", "US") == tuple(local.places[i] for i in ids)


def test_bundled_snapshot_integrity():
    data = files("oria_engine").joinpath("data")
    manifest = json.loads(data.joinpath("manifest.json").read_text())
    for name, checksum in manifest["outputs_sha256"].items():
        assert hashlib.sha256(data.joinpath(name).read_bytes()).hexdigest() == checksum
    payload = json.loads(gzip.decompress(data.joinpath("places.json.gz").read_bytes()))
    assert len(payload["places"]) == manifest["city_count"]
    assert len(payload["places"]) > 20000


@pytest.mark.parametrize(
    ("day", "clock", "zone", "expected"),
    [
        ("1990-04-13", "03:42", "Europe/Bucharest", ["1990-04-13T00:42:00+00:00"]),
        (
            "2020-11-01",
            "01:30",
            "America/New_York",
            [
                "2020-11-01T05:30:00+00:00",
                "2020-11-01T06:30:00+00:00",
            ],
        ),
        ("2020-03-08", "02:30", "America/New_York", []),
        (
            "2020-10-25",
            "03:30",
            "Europe/Bucharest",
            [
                "2020-10-25T00:30:00+00:00",
                "2020-10-25T01:30:00+00:00",
            ],
        ),
        (
            "2020-04-05",
            "01:45",
            "Australia/Lord_Howe",
            [
                "2020-04-04T14:45:00+00:00",
                "2020-04-04T15:15:00+00:00",
            ],
        ),
        ("2020-10-04", "02:15", "Australia/Lord_Howe", []),
        ("2011-12-30", "12:00", "Pacific/Apia", []),
        ("1985-01-01", "12:00", "Asia/Kathmandu", ["1985-01-01T06:30:00+00:00"]),
        ("1990-01-01", "12:00", "Asia/Kathmandu", ["1990-01-01T06:15:00+00:00"]),
    ],
)
def test_historical_conversion(day, clock, zone, expected):
    assert [
        d.isoformat()
        for d in utc_candidates(date.fromisoformat(day), time.fromisoformat(clock), zone)
    ] == expected


def test_no_host_timezone_fallback_or_silent_choice():
    from zoneinfo import ZoneInfoNotFoundError

    with pytest.raises(ZoneInfoNotFoundError):
        birth_zone("../etc/passwd")
    day, clock, zone = date(2020, 11, 1), time(1, 30), "America/New_York"
    with pytest.raises(ValueError, match="clarification"):
        resolve_utc(day, clock, zone)
    assert resolve_utc(day, clock, zone, 1) == datetime(2020, 11, 1, 6, 30, tzinfo=UTC)
    assert resolve_utc(day, None, zone) is None
    with pytest.raises(ValueError, match="does not exist"):
        resolve_utc(date(2020, 3, 8), time(2, 30), zone)
    with pytest.raises(ValueError):
        utc_candidates(day, time(1, 30, tzinfo=UTC), zone)
    with pytest.raises(ValueError):
        resolve_utc(day, time(12), zone, 1)


async def test_clarification_schema_and_encryption(resolver, encryption):
    place = (await resolver.resolve("New York City", "US"))[0]
    draft = OnboardingDraft(
        consent_id=uuid4(),
        birth_date=date(2020, 11, 1),
        birth_local_time=time(1, 30),
        birth_time_accuracy="approximate",
        birth_place=place,
    )
    assert resolve_state(draft) == State.BIRTH_TIME_CLARIFICATION
    assert "UTC-0400" in reply_for(draft).buttons[0].text
    assert all(len(b.data.encode()) <= 64 for b in reply_for(draft).buttons)
    with pytest.raises(ValidationError):
        draft.profile()
    selected = draft.model_copy(update={"birth_time_occurrence": 1})
    profile = selected.profile()
    assert profile.schema_version == 2
    assert profile.birth_local_time == time(1, 30)
    assert profile.utc_instant() == datetime(2020, 11, 1, 6, 30, tzinfo=UTC)
    context = {"user_id": uuid4(), "profile_id": uuid4()}
    encrypted = encryption.encrypt(profile, **context)
    assert encryption.decrypt(encrypted, **context, schema_version=2, key_version="v1") == profile
    for update in (
        {"birth_time_occurrence": 2},
        {"birth_local_time": None, "birth_time_accuracy": "unknown"},
        {"birth_date": "2020-03-08", "birth_local_time": "02:30"},
        {"birth_date": "2020-11-02"},
    ):
        with pytest.raises(ValidationError):
            BirthProfilePayload.model_validate(profile.model_dump() | update)


def test_legacy_payload_readable_without_new_field(encryption, birth_payload):
    legacy = birth_payload.model_dump(exclude={"birth_time_occurrence"})
    assert BirthProfilePayload.model_validate(legacy) == birth_payload
    context = {"user_id": uuid4(), "profile_id": uuid4()}
    encrypted = encryption.encrypt(birth_payload, **context)
    assert (
        encryption.decrypt(encrypted, **context, schema_version=1, key_version="v1")
        == birth_payload
    )
    assert birth_payload.utc_instant() == datetime(1990, 4, 13, 0, 42, tzinfo=UTC)
