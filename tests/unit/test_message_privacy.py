import pytest

from oria_engine.domain.consent import DISCLAIMER
from oria_engine.privacy.messages import prepare_active_input, private_active_input


@pytest.mark.parametrize(
    "text",
    [
        "Contact me at person@example.invalid",
        "+40 (700) 123 456",
        "My name is Example",
        "I live in Exampletown",
        "12 Example Street",
        "https://example.invalid/me",
        "My ｅｍａｉｌ is private",
        "I work for Example",
        "tomorrow at 15:30",
        "My cat died and I miss her",
    ],
)
def test_voluntary_personal_context_is_not_a_refusal(text):
    assert not private_active_input(text)
    assert prepare_active_input(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "My password is synthetic",
        "api_key=synthetic",
        "My access token: synthetic",
        "My ｐａｓｓｗｏｒｄ is synthetic",
        "My cvv is 123",
    ],
)
def test_obvious_secrets_stay_local(text):
    assert private_active_input(text)


@pytest.mark.parametrize(
    "text",
    [
        "I was born in Exampletown",
        "My birth time is 12:30",
        "birthday 1990-04-13",
        "I'd like you to rate my compatibility with my girlfriend. Her birthday is 1992-06-14",
        "She was born in Exampletown. 1992-06-14 at 12:30; 47.1, 23.6",
        "She was ｂｏｒｎ in Exampletown. 1992-06-14 at 12:30; 47.1, 23.6",
        "She was bo\u200brn in Exampletown. In Exampletown. At 12:30.",
    ],
)
def test_birth_inputs_are_held_without_a_privacy_refusal_or_external_forwarding(text):
    assert not private_active_input(text)
    filtered = prepare_active_input(text)
    assert filtered != text
    assert "Birth inputs held locally" in filtered
    assert prepare_active_input(filtered) == filtered
    for raw in ["Exampletown", "1990-04-13", "1992-06-14", "12:30", "47.1", "23.6"]:
        assert raw not in filtered


def test_compatibility_goal_is_preserved_without_fabricated_facts():
    filtered = prepare_active_input("Rate my compatibility with my wife, born 1992-06-14")
    assert "compatibility rating" in filtered
    assert "no additional calculation" in filtered
    assert "/edit_profile" not in filtered


def test_disclosure_fits_telegram_and_describes_current_capabilities():
    assert len(("Policy " + "v" * 64 + "\n\n" + DISCLAIMER).encode("utf-16-le")) // 2 <= 4096
    assert "You are responsible" in DISCLAIMER
    assert "remote selective erasure are not available yet" in DISCLAIMER
    assert "provenance are encrypted locally" in DISCLAIMER
    assert "Inspection and removal remain available" in DISCLAIMER
    assert "do not include identifying" not in DISCLAIMER


def test_clock_compatibility_flag_never_grants_secret_forwarding():
    assert not private_active_input("tomorrow at 15:30", resolved_clock=True)
    assert private_active_input("password=synthetic tomorrow at 15:30", resolved_clock=True)
