from uuid import uuid4

import pytest
from pydantic import ValidationError

from oria_engine.config import ConfigurationError, Settings
from oria_engine.domain.birth_profile import BirthProfilePayload
from oria_engine.privacy.encryption import ProfileEncryption, ProfileEncryptionError


def test_round_trip_and_fresh_nonces(encryption, birth_payload):
    context = dict(user_id=uuid4(), profile_id=uuid4())
    first = encryption.encrypt(birth_payload, **context)
    second = encryption.encrypt(birth_payload, **context)
    assert first[:12] != second[:12]
    assert encryption.decrypt(first, **context, schema_version=1, key_version="v1") == birth_payload
    for value in ("1990-04-13", "03:42:00", "Cluj-Napoca", "Europe/Bucharest"):
        assert value.encode() not in first
        assert value not in repr(birth_payload)
        assert value not in str(birth_payload)
        assert value not in repr(birth_payload.birth_place)


@pytest.mark.parametrize(
    "change", ["key", "user", "profile", "schema", "version", "tag", "nonce", "short"]
)
def test_authentication_failures_are_safe(encryption, birth_payload, change):
    context = dict(user_id=uuid4(), profile_id=uuid4(), schema_version=1, key_version="v1")
    encrypted = encryption.encrypt(
        birth_payload, user_id=context["user_id"], profile_id=context["profile_id"]
    )
    if change == "key":
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        encryption._cipher = AESGCM(AESGCM.generate_key(bit_length=256))
    elif change in {"user", "profile"}:
        context[f"{change}_id"] = uuid4()
    elif change == "schema":
        context["schema_version"] = 2
    elif change == "version":
        context["key_version"] = "v2"
    elif change == "tag":
        encrypted = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
    elif change == "nonce":
        encrypted = bytes([encrypted[0] ^ 1]) + encrypted[1:]
    else:
        encrypted = b"short"
    with pytest.raises(ProfileEncryptionError, match="Birth profile could not be decrypted"):
        encryption.decrypt(encrypted, **context)


def test_missing_key_fails_closed():
    with pytest.raises(ConfigurationError, match="configured key"):
        ProfileEncryption(Settings(_env_file=None))


@pytest.mark.parametrize("accuracy", ["exact", "approximate", "unknown"])
def test_time_accuracy(birth_payload, accuracy):
    values = birth_payload.model_dump()
    values["birth_time_accuracy"] = accuracy
    if accuracy == "unknown":
        values["birth_local_time"] = None
    assert BirthProfilePayload.model_validate(values).birth_time_accuracy == accuracy


@pytest.mark.parametrize(
    "values",
    [
        {"schema_version": 2},
        {"email": "synthetic@example.invalid"},
        {"birth_date": "1990-02-30"},
        {"birth_local_time": "25:00"},
        {"birth_local_time": "03:42:00+03:00"},
        {"birth_local_time": None},
        {"birth_time_accuracy": "unknown"},
        {"birth_time_accuracy": "guessed"},
    ],
)
def test_invalid_profile(birth_payload, values):
    with pytest.raises(ValidationError):
        BirthProfilePayload.model_validate(birth_payload.model_dump() | values)


@pytest.mark.parametrize(
    "values",
    [
        {"latitude": 91},
        {"longitude": -181},
        {"latitude": float("nan")},
        {"timezone": "Not/A_Zone"},
        {"country_code": "Romania"},
        {"city": "  "},
        {"street_address": "synthetic address"},
    ],
)
def test_invalid_place(birth_payload, values):
    data = birth_payload.model_dump()
    data["birth_place"].update(values)
    with pytest.raises(ValidationError) as error:
        BirthProfilePayload.model_validate(data)
    assert "Cluj-Napoca" not in str(error.value)


def test_constructed_invalid_models_cannot_bypass_encryption(encryption, birth_payload):
    invalid = birth_payload.model_copy(update={"birth_time_accuracy": "unknown"})
    with pytest.raises(ProfileEncryptionError, match="Invalid birth profile"):
        encryption.encrypt(invalid, user_id=uuid4(), profile_id=uuid4())
