from datetime import date, time
from uuid import uuid4

import pytest
from pydantic import ValidationError

from oria_engine.domain.consent import OnboardingState as State
from oria_engine.domain.onboarding import reply_for, resolve_state
from oria_engine.domain.onboarding_data import OnboardingDraft, parse_birth_date, parse_birth_time
from oria_engine.privacy.encryption import ProfileEncryptionError


@pytest.mark.parametrize("text", ["1990-04-13", "13 Apr 1990", "13 apr 1990"])
def test_date_formats(text):
    assert parse_birth_date(text) == date(1990, 4, 13)


@pytest.mark.parametrize(
    "text",
    [
        "04/05/1990",
        "13/04/1990",
        "1990-02-29",
        "31 Apr 1990",
        "1990-4-13",
        "tomorrow",
        "9999-01-01",
        "1990-04-13 email: private@example.test",
        "2000-01-01T00:00:00",
    ],
)
def test_reject_date_without_echo(text):
    with pytest.raises(ValueError) as error:
        parse_birth_date(text)
    assert text not in str(error.value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("03:42", (time(3, 42), "exact")),
        ("exact 03:42", (time(3, 42), "exact")),
        ("approximate 03:42", (time(3, 42), "approximate")),
        ("unknown", (None, "unknown")),
    ],
)
def test_time_formats(text, expected):
    assert parse_birth_time(text) == expected


@pytest.mark.parametrize(
    "text", ["24:00", "03:60", "3:42", "3pm", "noon", "03:42+03:00", "03:42 email"]
)
def test_reject_invalid_or_ambiguous_time(text):
    with pytest.raises(ValueError):
        parse_birth_time(text)


def test_draft_schema_state_and_privacy(birth_payload):
    draft = OnboardingDraft(consent_id=uuid4())
    assert resolve_state(draft) == State.BIRTH_DATE_REQUIRED
    assert resolve_state(None, profile_exists=True) == State.COMPUTING_PROFILE
    draft = draft.model_copy(update={"birth_date": birth_payload.birth_date})
    assert resolve_state(draft) == State.BIRTH_TIME_REQUIRED
    draft = draft.model_copy(update={"birth_time_accuracy": "unknown"})
    assert resolve_state(draft) == State.BIRTH_PLACE_REQUIRED
    draft = draft.model_copy(update={"candidates": (birth_payload.birth_place,)})
    assert resolve_state(draft) == State.BIRTH_PLACE_CONFIRMATION
    draft = draft.model_copy(update={"birth_place": birth_payload.birth_place, "candidates": ()})
    assert resolve_state(draft) == State.PROFILE_CONFIRMATION
    assert draft.profile().birth_local_time is None
    assert "1990" not in repr(draft)
    assert "Cluj" not in repr(reply_for(draft))
    assert all(len(b.data.encode()) <= 64 for b in reply_for(draft).buttons)
    for extra in ({"email": "private@example.test"}, {"birth_time_accuracy": "exact"}):
        with pytest.raises(ValidationError):
            OnboardingDraft.model_validate({**draft.model_dump(), **extra})


def test_draft_encryption_is_scoped_and_separate_from_final_profile(encryption, birth_payload):
    owner = uuid4()
    draft = OnboardingDraft(consent_id=uuid4(), **birth_payload.model_dump())
    encrypted = encryption.encrypt_draft(draft, user_id=owner)
    assert encrypted != encryption.encrypt_draft(draft, user_id=owner)
    assert b"1990-04-13" not in encrypted
    assert (
        encryption.decrypt_draft(encrypted, user_id=owner, key_version="v1", schema_version=1)
        == draft
    )
    for data, user, version, schema in [
        (encrypted, uuid4(), "v1", 1),
        (encrypted, owner, "v2", 1),
        (encrypted, owner, "v1", 2),
        (b"short", owner, "v1", 1),
        (encrypted[:-1] + bytes([encrypted[-1] ^ 1]), owner, "v1", 1),
        (encryption.encrypt(birth_payload, user_id=owner, profile_id=owner), owner, "v1", 1),
    ]:
        with pytest.raises(ProfileEncryptionError):
            encryption.decrypt_draft(data, user_id=user, key_version=version, schema_version=schema)
    with pytest.raises(ProfileEncryptionError):
        encryption.encrypt_draft(draft.model_copy(update={"birth_date": "bad"}), user_id=owner)
