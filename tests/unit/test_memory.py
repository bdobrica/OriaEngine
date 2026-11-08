"""Memory candidates are user assertions, not model instructions or date questions."""

import pytest

from oria_engine.domain.memory import directive, entity_from, extract_events, privacy_control


@pytest.mark.parametrize(
    ("text", "types"),
    [
        ("We married May 1st, 2020", ["wedding"]),
        ("I bought my house in May 2020", ["purchase"]),
        ("I got the cat exactly nine months ago", ["adoption"]),
        ("I changed my job yesterday", ["job change"]),
        ("I founded my business on May 1st, 2020", ["founding"]),
        ("My parents got divorced this day last year", ["divorce"]),
        ("My girlfriend Alice was born June 2nd, 1992", ["birth"]),
        (
            "We married May 1st, 2020 and my girlfriend was born June 2nd, 1992",
            ["wedding", "birth"],
        ),
        ("Remember that I won a prize in 2020", ["life event"]),
    ],
)
def test_meaningful_events(text, types):
    assert [event.event_type for event in extract_events(text)] == types


@pytest.mark.parametrize(
    "text",
    [
        "If we married May 1st, 2020",
        "Imagine we married tomorrow",
        "We did not get married in 2020",
        "When did we get married?",
        "What if my girlfriend was born in 1992?",
        "I might adopt a cat tomorrow",
        '"We married May 1st, 2020"',
        "For example, we married last year",
        "Don't remember this; we married May 1st, 2020",
        "My birthday is April 13th, 1990",
    ],
)
def test_non_assertions_and_own_profile_are_not_learned(text):
    assert not extract_events(text)


def test_entities_are_local_candidates_and_named_aliases():
    candidate = entity_from("my girlfriend Alice was born yesterday")
    assert candidate.label == "Alice"
    assert candidate.aliases == ("my girlfriend",)
    assert candidate.relationship == "girlfriend"
    assert entity_from("my cat Luna").entity_type == "pet"
    assert entity_from("my company Nova").entity_type == "organization"
    assert entity_from("my car").entity_type == "possession"


def test_privacy_controls_are_distinct_from_learning():
    assert privacy_control("forget my girlfriend's birthday")
    assert privacy_control("what do you remember about our wedding?")
    assert not privacy_control("actually, it was May 2nd, 2020")
    assert not privacy_control("remember our wedding")
    assert directive("don't remember this") is None


@pytest.mark.parametrize(
    "text", ["We married May 1st, 2020?", "My girlfriend Alice was born June 2nd, 1992?"]
)
def test_questions_are_not_disclosures_even_without_a_question_word(text):
    assert not extract_events(text)


def test_lowercase_birth_name_and_explicit_reading_request():
    from oria_engine.domain.memory import requested_follow_up

    assert entity_from("my girlfriend alice was born June 2nd, 1992").label == "alice"
    assert (
        requested_follow_up("We married May 1st, 2020. Rate our compatibility.")
        == "Rate our compatibility"
    )
    assert requested_follow_up("We married May 1st, 2020") is None


def test_lookup_matches_whole_words_and_does_not_select_unrelated_records():
    from uuid import uuid4

    from oria_engine.db.knowledge import SavedRecord
    from oria_engine.domain.knowledge import matches
    from oria_engine.knowledge.contracts import EventRecord

    education = SavedRecord(
        EventRecord(
            id=uuid4(),
            revision=1,
            event_type="life event",
            description="my education",
            source_message_id=uuid4(),
        )
    )
    wedding = SavedRecord(
        EventRecord(
            id=uuid4(),
            revision=1,
            event_type="wedding",
            description="our wedding",
            source_message_id=uuid4(),
        )
    )
    assert not matches("my cat", education)
    assert matches("we got married", wedding)
