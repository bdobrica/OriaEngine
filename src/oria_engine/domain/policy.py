"""Deterministic English demo policy. No input, draft or matched value is logged."""

import re
import unicodedata
from typing import Final

# User-supplied birth fields only; coordinates/timezone come from the local resolver.
# Occurrence is the deterministic clarification of a repeated local time.
ONBOARDING_FIELDS: Final = frozenset(
    {
        "birth_date",
        "birth_local_time",
        "birth_time_accuracy",
        "birth_place",
        "birth_time_occurrence",
    }
)

PRIVACY_REPLY: Final = (
    "I can work with the context you've chosen to share; "
    "no passwords or extra identifying details are needed."
)
SAFETY_REPLY: Final = (
    "I can't help with instructions or encouragement to harm you, others, animals or property. "
    "We can talk through what's happening and explore another way forward."
)
FACTS_REPLY: Final = (
    "I don't have facts that establish that outcome. "
    "We can explore your question without treating an interpretation as certainty."
)
CAPABILITY_REPLY: Final = (
    "We can discuss this here, but I haven't changed any stored details. "
    "Saving or selectively forgetting life events isn't available yet."
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return re.sub(r"\s+", " ", text)


# Match collection behavior, not mentions of PII or relevant entity labels.
IDENTIFIER = (
    r"(?:legal[ -]?name|full[ -]?name|e[ -]?mail(?: address)?|phone number|"
    r"telephone number|(?:home|postal|mailing|street|residential) address|"
    r"account (?:id|identifier|number)|government (?:id|identifier)|"
    r"social security(?: number)?|ssn|passport(?: number)?|"
    r"password|passcode|pin code|credentials|payment details|"
    r"credit card|debit card|card number|cvv|iban|bank details)"
)
SOLICITATION = re.compile(
    r"\b(?:tell|send|share|provide|enter|give|confirm|need|collect)\s+"
    r"(?:(?:me|us)\s+)?(?:(?:your|the)\s+)?"
    + IDENTIFIER
    + r"\b|\b(?:what is|what's|may i have|can i have)\s+(?:your|the)\s+"
    + IDENTIFIER
    + r"\b"
)
NEGATED = re.compile(
    r"\b(?:don't|do not|never|not to|avoid|without|can't|cannot|shouldn't|should not)\s+$|"
    r"\bno (?:evidence|reason|basis) (?:that|to believe that)\s+$|"
    r"\bdoes(?:n't| not) mean (?:that )?$"
)
TARGET = (
    r"(?:myself|yourself|someone|anyone|people|a person|an animal|"
    r"(?:my|your|his|her|their|the|a) (?:partner|wife|husband|girlfriend|boyfriend|"
    r"child|children|parents?|cat|dog|pet|neighbor|neighbour|boss|coworker|"
    r"business|company|non-profit|house|car|phone))"
)
HARM_ACTION = r"(?:kill|murder|hurt|poison|abuse|injure|attack|torture|sabotage|destroy|burn down)"
HARM_REQUEST = re.compile(
    r"\b(?:how (?:can|do|should) i|how to|help me|teach me to|"
    r"i (?:want|plan|intend) to|should i)\s+"
    r"(?:(?:intentionally|deliberately|secretly|quickly|quietly|physically|emotionally|actually)\s+){0,2}"
    + HARM_ACTION
    + r"\s+"
    + TARGET
    + r"\b|"
    r"\b(?:ways?|instructions?|steps?) to\s+" + HARM_ACTION + r"\s+" + TARGET + r"\b|"
    r"\b(?:how to|help me|teach me to) (?:\w+\s+){0,3}hack into "
    r"(?:her|his|their|someone else's) (?:account|phone|email)\b"
)
HARM_DIRECTION = re.compile(
    r"\b(?:you should|you must|go ahead and|i recommend you)\s+"
    + HARM_ACTION
    + r"\s+"
    + TARGET
    + r"\b|"
    r"(?:^|[.!?]\s+)(?:" + HARM_ACTION + r")\s+" + TARGET + r"\b|"
    r"\b(?:stop taking|stop your|double your) (?:\w+\s+){0,2}"
    r"(?:medication|medicine|dose)\b|"
    r"\b(?:invest|bet|trade) all (?:of )?your (?:savings|money)\b|"
    r"\btrade these stocks\b"
)
UNSUPPORTED_CLAIM = re.compile(
    r"\byou will (?:definitely |certainly )?(?:die|lose all your money)\b|"
    r"\byour (?:partner|spouse|relationship) will (?:definitely |certainly )?"
    r"(?:leave|cheat|fail|end)\b|"
    r"\b(?:pregnancy|an accident) is (?:certain|inevitable|guaranteed)\b|"
    r"\b(?:your|the) chart (?:confirms?|proves?|diagnoses?) "
    r"(?:a disease|cancer|criminality|pregnancy|an illness)\b|"
    r"\bthis investment will (?:certainly|definitely) make you rich\b|"
    r"\bthe court will (?:definitely|certainly) rule for you\b"
)
UNCONFIRMED_ACTION = re.compile(
    r"\bi(?:'ve| have| just)? (?:saved|stored|updated|changed|corrected|deleted|erased|forgotten) "
    r"(?:this|that|your|the (?:event|record|profile|memory|details))\b|"
    r"\bi(?:'ll| will) remember (?:this|that|your|what you)\b"
)


def _affirmative_match(pattern: re.Pattern[str], value: str) -> bool:
    # Negating one action never exempts a later affirmative request/claim.
    return any(
        not NEGATED.search(value[max(0, m.start() - 64) : m.start()])
        for m in pattern.finditer(value)
    )


def is_harmful_request(text: str) -> bool:
    """Bounded English patterns for explicit harmful requests, not topic classification."""
    return _affirmative_match(HARM_REQUEST, normalize(text))


def guard_reply(draft: str) -> str:
    """Narrow behavioral backstop; prompts handle context beyond these English patterns.

    This is not semantic safety proof, a PII scrubber or authorization for any action.
    A blocked draft is replaced completely and never logged or partially delivered.
    """
    value = normalize(draft)
    if _affirmative_match(SOLICITATION, value):
        return PRIVACY_REPLY
    if _affirmative_match(HARM_DIRECTION, value) or is_harmful_request(value):
        return SAFETY_REPLY
    if _affirmative_match(UNSUPPORTED_CLAIM, value):
        return FACTS_REPLY
    if _affirmative_match(UNCONFIRMED_ACTION, value):
        return CAPABILITY_REPLY
    return draft
