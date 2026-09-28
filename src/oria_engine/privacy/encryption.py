"""AES-256-GCM envelope v1: 12-byte random nonce followed by ciphertext and tag."""

import base64
import json
import os
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import ValidationError

from oria_engine.config import ConfigurationError, Settings
from oria_engine.domain.birth_profile import BirthProfilePayload
from oria_engine.domain.onboarding_data import OnboardingDraft


class ProfileEncryptionError(ValueError):
    """Payload-free encryption/decoding diagnostic."""


class ProfileEncryption:
    def __init__(self, settings: Settings) -> None:
        key = settings.profile_encryption_key.get_secret_value()
        if not key:
            raise ConfigurationError("Profile encryption requires a configured key")
        self._cipher = AESGCM(base64.b64decode(key, altchars=b"-_", validate=True))
        self.key_version = settings.profile_encryption_key_version

    def _draft_aad(self, user_id: UUID) -> bytes:
        return json.dumps(
            ["oria:onboarding-draft:aes256gcm:v1", str(user_id), 1, self.key_version],
            separators=(",", ":"),
        ).encode()

    def encrypt_draft(self, draft: OnboardingDraft, *, user_id: UUID) -> bytes:
        try:
            validated = OnboardingDraft.model_validate(draft)
        except ValidationError:
            raise ProfileEncryptionError("Invalid onboarding draft") from None
        nonce = os.urandom(12)
        return nonce + self._cipher.encrypt(
            nonce, validated.model_dump_json().encode(), self._draft_aad(user_id)
        )

    def decrypt_draft(
        self, encrypted_payload: bytes, *, user_id: UUID, key_version: str, schema_version: int
    ) -> OnboardingDraft:
        try:
            if (
                key_version != self.key_version
                or schema_version != 1
                or len(encrypted_payload) < 29
            ):
                raise ValueError()
            plaintext = self._cipher.decrypt(
                encrypted_payload[:12], encrypted_payload[12:], self._draft_aad(user_id)
            )
            return OnboardingDraft.model_validate_json(plaintext)
        except (InvalidTag, ValueError):
            raise ProfileEncryptionError("Onboarding draft could not be decrypted") from None

    def _aad(self, user_id: UUID, profile_id: UUID, schema_version: int) -> bytes:
        return json.dumps(
            [
                "oria:birth-profile:aes256gcm:v1",
                str(user_id),
                str(profile_id),
                schema_version,
                self.key_version,
            ],
            separators=(",", ":"),
        ).encode()

    def encrypt(self, payload: BirthProfilePayload, *, user_id: UUID, profile_id: UUID) -> bytes:
        try:
            # Revalidate even model_construct/model_copy results at the persistence boundary.
            validated = BirthProfilePayload.model_validate(payload)
        except ValidationError:
            raise ProfileEncryptionError("Invalid birth profile") from None
        nonce = os.urandom(12)
        return nonce + self._cipher.encrypt(
            nonce,
            validated.model_dump_json(
                exclude={"birth_time_occurrence"} if validated.schema_version == 1 else None
            ).encode(),
            self._aad(user_id, profile_id, validated.schema_version),
        )

    def decrypt(
        self,
        encrypted_payload: bytes,
        *,
        user_id: UUID,
        profile_id: UUID,
        schema_version: int,
        key_version: str,
    ) -> BirthProfilePayload:
        try:
            if (
                key_version != self.key_version
                or schema_version not in (1, 2)
                or len(encrypted_payload) < 29
            ):
                raise ValueError()
            plaintext = self._cipher.decrypt(
                encrypted_payload[:12],
                encrypted_payload[12:],
                self._aad(user_id, profile_id, schema_version),
            )
            payload = BirthProfilePayload.model_validate_json(plaintext)
            if payload.schema_version != schema_version:
                raise ValueError()
            return payload
        except (InvalidTag, ValueError):
            raise ProfileEncryptionError("Birth profile could not be decrypted") from None

    def encrypt_event(self, value: str, *, user_id: UUID, event_id: UUID, kind: str) -> bytes:
        nonce = os.urandom(12)
        aad = self._event_aad(user_id, event_id, kind)
        return nonce + self._cipher.encrypt(nonce, value.encode(), aad)

    def decrypt_event(
        self, value: bytes, *, user_id: UUID, event_id: UUID, kind: str, key_version: str
    ) -> str:
        try:
            if key_version != self.key_version or len(value) < 29:
                raise ValueError()
            return self._cipher.decrypt(
                value[:12], value[12:], self._event_aad(user_id, event_id, kind)
            ).decode()
        except (InvalidTag, ValueError):
            raise ProfileEncryptionError("Queued payload could not be decrypted") from None

    def _event_aad(self, user_id: UUID, event_id: UUID, kind: str) -> bytes:
        return json.dumps(
            ["oria:event:v1", str(user_id), str(event_id), kind, self.key_version]
        ).encode()
