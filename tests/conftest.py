"""Synthetic birth-profile fixtures; encryption keys are generated per test."""

import base64

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from oria_engine.config import Settings
from oria_engine.domain.birth_profile import BirthProfilePayload
from oria_engine.privacy.encryption import ProfileEncryption


@pytest.fixture
def birth_payload():
    return BirthProfilePayload.model_validate(
        {
            "birth_date": "1990-04-13",
            "birth_local_time": "03:42:00",
            "birth_time_accuracy": "exact",
            "birth_place": {
                "display_name": "Cluj-Napoca, RO",
                "city": "Cluj-Napoca",
                "region": "Cluj",
                "country_code": "RO",
                "latitude": 46.7712,
                "longitude": 23.6236,
                "timezone": "Europe/Bucharest",
            },
        }
    )


@pytest.fixture
def encryption():
    return ProfileEncryption(
        Settings(
            _env_file=None,
            profile_encryption_key=base64.b64encode(AESGCM.generate_key(bit_length=256)).decode(),
        )
    )
