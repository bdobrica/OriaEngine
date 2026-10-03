import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from oria_engine.app import create_app
from oria_engine.config import Settings
from oria_engine.context.contracts import ContextReply, ContextScope, ConversationRequest
from oria_engine.context.service import ConversationContext
from oria_engine.domain.active import route_active
from oria_engine.domain.birth_profile import BirthProfilePayload
from oria_engine.domain.policy import (
    ONBOARDING_FIELDS,
    PRIVACY_REPLY,
    SAFETY_REPLY,
    guard_reply,
    is_high_stakes,
)

CORPUS = json.loads((Path(__file__).parent / "fixtures/policy-adversarial.json").read_text())


@pytest.mark.parametrize("case", CORPUS)
async def test_adversarial_application_boundary(case, caplog):
    provider = AsyncMock()
    # Simulate a compromised model obeying hostile input or retrieved memory.
    provider.respond.return_value = ContextReply(response_id="synthetic", text=case["draft"])
    scope = ContextScope(user_id=uuid4(), session_id=uuid4())
    with patch("oria_engine.context.service.ConversationSessionRepository") as repository:
        repository.return_value.get_or_create = AsyncMock(return_value=scope)
        reply = await ConversationContext(provider, "test").respond(
            AsyncMock(), scope.user_id, ConversationRequest(filtered_message=case["input"])
        )
    expected = PRIVACY_REPLY if case["kind"] == "privacy" else SAFETY_REPLY
    assert reply.text == expected
    assert guard_reply(case["draft"]) == expected
    assert case["draft"] not in caplog.text
    if is_high_stakes(case["input"]):
        provider.respond.assert_not_awaited()
        assert route_active(case["input"], received_at=datetime.now(UTC)).kind == (
            "unsupported_high_stakes"
        )
    else:
        provider.respond.assert_awaited_once()


@pytest.mark.parametrize(
    "field",
    [
        "legal name",
        "full name",
        "email",
        "phone number",
        "home address",
        "postal address",
        "employer",
        "account identifier",
        "government ID",
        "password",
        "payment details",
        "passport",
        "SSN",
        "credit card",
        "IBAN",
        "your name",
        "birth date",
        "birth time",
        "birthplace",
        "date of birth",
        "ＥＭＡＩＬ",
        "e\u200bmail",
        "e-mail",
    ],
)
def test_common_solicitations(field):
    assert guard_reply(f"Please share {field}. It will help my reading.") == PRIVACY_REPLY


@pytest.mark.parametrize(
    "draft",
    [
        "What would you like to reflect on?",
        "Your Sun is in Cancer. This is an interpretive theme, not a prediction.",
        "Birth time is unknown: houses and angles are unavailable.",
        "Use /edit_profile to correct your birth details.",
        "Your approximate birth time makes this placement uncertain.",
    ],
)
def test_allowed_reflection_and_uncertainty(draft):
    assert guard_reply(draft) == draft


def test_negation_and_quotes_cannot_hide_an_unsafe_request():
    assert guard_reply("Don't share your email. Actually, send it now.") == PRIVACY_REPLY
    assert guard_reply('The memory says: "Tell me your password".') == PRIVACY_REPLY
    assert guard_reply("Not a prediction, but you will die tomorrow.") == SAFETY_REPLY


def test_closed_profile_fields_and_http_surface():
    assert set(BirthProfilePayload.model_fields) == ONBOARDING_FIELDS | {"schema_version"}
    assert BirthProfilePayload.model_config["extra"] == "forbid"
    schema = create_app(Settings(_env_file=None)).openapi()
    assert set(schema["paths"]) == {"/healthz", "/readyz"}
    assert all(set(path) == {"get"} for path in schema["paths"].values())


async def test_allowed_service_reply_preserves_text_and_id():
    provider = AsyncMock()
    provider.respond.return_value = ContextReply(response_id="test", text="A reflective theme.")
    scope = ContextScope(user_id=uuid4(), session_id=uuid4())
    with patch("oria_engine.context.service.ConversationSessionRepository") as repository:
        repository.return_value.get_or_create = AsyncMock(return_value=scope)
        result = await ConversationContext(provider, "test").respond(
            AsyncMock(), scope.user_id, ConversationRequest(filtered_message="Explain my chart")
        )
    assert result == provider.respond.return_value
