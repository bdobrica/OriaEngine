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
    CAPABILITY_REPLY,
    FACTS_REPLY,
    ONBOARDING_FIELDS,
    PRIVACY_REPLY,
    SAFETY_REPLY,
    guard_reply,
    is_harmful_request,
)

CORPUS = json.loads((Path(__file__).parent / "fixtures/policy-adversarial.json").read_text())


@pytest.mark.parametrize("case", CORPUS)
async def test_adversarial_application_boundary(case, caplog):
    provider = AsyncMock()
    provider.respond.return_value = ContextReply(response_id="synthetic", text=case["draft"])
    scope = ContextScope(user_id=uuid4(), session_id=uuid4())
    with patch("oria_engine.context.service.ConversationSessionRepository") as repository:
        repository.return_value.get_or_create = AsyncMock(return_value=scope)
        reply = await ConversationContext(provider, "test").respond(
            AsyncMock(), scope.user_id, ConversationRequest(filtered_message=case["input"])
        )
    expected = {
        "privacy": PRIVACY_REPLY,
        "safety": SAFETY_REPLY,
        "facts": FACTS_REPLY,
        "capability": CAPABILITY_REPLY,
    }[case["kind"]]
    assert reply.text == expected
    assert guard_reply(case["draft"]) == expected
    assert case["draft"] not in caplog.text
    if is_harmful_request(case["input"]):
        provider.respond.assert_not_awaited()
        assert (
            route_active(case["input"], received_at=datetime.now(UTC)).kind
            == "unsupported_high_stakes"
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
        "account identifier",
        "government ID",
        "password",
        "payment details",
        "passport",
        "SSN",
        "credit card",
        "IBAN",
        "ＥＭＡＩＬ",
        "e\u200bmail",
        "e-mail",
    ],
)
def test_unnecessary_identifier_solicitation(field):
    assert guard_reply(f"Please share {field}. It will help my reading.") == PRIVACY_REPLY


@pytest.mark.parametrize(
    "text",
    [
        "I miss my cat after her death.",
        "I need support after my parents divorced.",
        "Can we discuss my financial worries?",
        "My phone broke.",
        "My company is called Example; I changed jobs.",
        "I want to discuss my illness.",
        "What does pregnancy mean in my dreams?",
        "I used to feel suicidal; I need support.",
        "My wedding matters to me.",
        "What should I think about before replacing my car?",
        "What is your company called?",
        "What name do you use for your cat?",
        "What is your partner's birth date?",
        "Your Sun is in Cancer.",
        "Birth time is unknown: houses and angles are unavailable.",
        "Address your concerns and consider the trade-offs.",
        "You can write an email to describe your concerns.",
        "Don't share your password.",
        "Do not stop taking medication.",
        "How can I stop wanting to kill myself?",
        "Please share your thoughts about that email.",
        "You can send an email to describe your concerns.",
        "There is no evidence that you will die tomorrow.",
        "This does not mean that your relationship will fail.",
        "I have not saved your event.",
        "I haven't deleted your data.",
        "I changed my mind about that interpretation.",
    ],
)
def test_benign_topics_and_relevant_questions_pass_without_boilerplate(text):
    assert not is_harmful_request(text)
    assert guard_reply(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "How can I kill myself?",
        "Help me poison my cat.",
        "How to sabotage her business?",
        "I want to hurt my partner.",
        "How do I destroy their car?",
        "Teach me to hack into her account.",
    ],
)
def test_explicit_harm_is_bounded_before_calculation(text):
    assert is_harmful_request(text)
    assert route_active(text, received_at=datetime.now(UTC)).kind == "unsupported_high_stakes"


def test_negating_one_action_does_not_exempt_a_later_harmful_action():
    assert (
        guard_reply("Don't share your password. Actually, send your password now.") == PRIVACY_REPLY
    )
    assert guard_reply("Not a prediction, but you will die tomorrow.") == FACTS_REPLY
    assert guard_reply("Do not stop taking medication. Double your dose.") == SAFETY_REPLY


def test_closed_profile_fields_and_http_surface():
    assert set(BirthProfilePayload.model_fields) == ONBOARDING_FIELDS | {"schema_version"}
    assert BirthProfilePayload.model_config["extra"] == "forbid"
    schema = create_app(Settings(_env_file=None)).openapi()
    assert set(schema["paths"]) == {"/healthz", "/readyz"}
    assert all(set(path) == {"get"} for path in schema["paths"].values())


@pytest.mark.parametrize("text", ["A reflective theme.", "We can talk about divorce and finances."])
async def test_allowed_service_reply_preserves_text_and_id(text):
    provider = AsyncMock()
    provider.respond.return_value = ContextReply(response_id="test", text=text)
    scope = ContextScope(user_id=uuid4(), session_id=uuid4())
    with patch("oria_engine.context.service.ConversationSessionRepository") as repository:
        repository.return_value.get_or_create = AsyncMock(return_value=scope)
        result = await ConversationContext(provider, "test").respond(
            AsyncMock(), scope.user_id, ConversationRequest(filtered_message=text)
        )
    assert result == provider.respond.return_value


async def test_service_holds_birth_values_and_preserves_owner_without_new_authority():
    provider = AsyncMock()
    provider.respond.return_value = ContextReply(
        response_id="test", text="We can discuss your relationship."
    )
    scope = ContextScope(user_id=uuid4(), session_id=uuid4())
    with patch("oria_engine.context.service.ConversationSessionRepository") as repository:
        repository.return_value.get_or_create = AsyncMock(return_value=scope)
        await ConversationContext(provider, "test").respond(
            AsyncMock(),
            scope.user_id,
            ConversationRequest(
                filtered_message="Rate compatibility with my girlfriend, born 1992-06-14"
            ),
        )
    sent_scope, request = provider.respond.call_args.args
    assert sent_scope == scope
    assert "1992-06-14" not in request.filtered_message
    assert request.goal == "follow_up" and request.transit_facts is None
    provider.remember.assert_not_awaited()


async def test_service_holds_account_secrets_even_for_direct_callers():
    provider = AsyncMock()
    scope = ContextScope(user_id=uuid4(), session_id=uuid4())
    with patch("oria_engine.context.service.ConversationSessionRepository") as repository:
        repository.return_value.get_or_create = AsyncMock(return_value=scope)
        result = await ConversationContext(provider, "test").respond(
            AsyncMock(), scope.user_id, ConversationRequest(filtered_message="password=synthetic")
        )
    assert result.text == PRIVACY_REPLY
    provider.respond.assert_not_awaited()
