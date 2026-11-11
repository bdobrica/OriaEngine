import pytest

from oria_engine.domain.reading_focus import FOLLOW_UP


@pytest.mark.parametrize(
    "text",
    [
        "What does it mean in plain English?",
        "Please explain that in simpler terms.",
        "Tell me more about this",
        "Make it shorter",
        "Why?",
    ],
)
def test_bounded_references_to_the_current_reading(text):
    assert FOLLOW_UP.fullmatch(text)


@pytest.mark.parametrize(
    "text",
    [
        "What does tomorrow mean for me?",
        "Tell me more about rainbows",
        "What is my compatibility with someone else?",
        "Explain that. Now compare me with Alice",
        "Don't remember this. What does it mean?",
        "1992-06-02",
    ],
)
def test_new_topics_private_inputs_and_opt_out_do_not_select_the_old_reading(text):
    assert not FOLLOW_UP.fullmatch(text)
