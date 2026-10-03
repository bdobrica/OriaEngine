import pytest

from oria_engine.domain.consent import DISCLAIMER
from oria_engine.privacy.messages import private_active_input


@pytest.mark.parametrize(
    "text",
    [
        "Contact me at person@example.invalid",
        "+40 (700) 123 456",
        "My name is Example",
        "I was born in Exampletown",
        "My birth time is 12:30",
        "My password is synthetic",
        "I live in Exampletown",
        "12 Example Street",
        "https://example.invalid/me",
        "My ｅｍａｉｌ is private",
        "I work for Example",
        "birthday 1990-04-13",
    ],
)
def test_sensitive_messages_stay_local(text):
    assert private_active_input(text)


@pytest.mark.parametrize(
    "text",
    [
        "Explain my natal chart",
        "Tell me more",
        "transits on 2026-10-02",
        "My birth time is unknown",
        "What does Venus in Taurus mean?",
    ],
)
def test_ordinary_chat(text):
    # Even uncertainty statements with a birth-field label are conservatively local.
    assert private_active_input(text) == (text == "My birth time is unknown")


def test_disclosure_fits_telegram():
    assert len(("Policy " + "v" * 64 + "\n\n" + DISCLAIMER).encode("utf-16-le")) // 2 <= 4096
