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
    "Let's keep this conversation to chart interpretation and reflection. "
    "Please keep unrelated identifying details private. "
    "To change your birth details, use /edit_profile."
)
SAFETY_REPLY: Final = (
    "I can't use astrology to predict high-stakes outcomes or guide medical, legal "
    "or financial decisions. Please use appropriate professional support for those "
    "decisions. I can show calculated chart facts for low-stakes reflection."
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return re.sub(r"\s+", " ", text)


# Conservative category mentions, including quoted/negated requests, are blocked.
# Do not attempt to strip one unsafe sentence and send the rest of a model draft.
PII = re.compile(
    r"\b(full[ -]?name|legal[ -]?name|first[ -]?name|last[ -]?name|surname|"
    r"your name|e[ -]?mail|phone|telephone|mobile|contact details|address|"
    r"(?:home|postal|mailing|street|residential)[ -]?address|post[ -]?code|zip[ -]?code|"
    r"employer|workplace|company name|where (?:do you|you) (?:work|live)|"
    r"account (?:id|identifier|number|name)|user[ -]?name|"
    r"government (?:id|identifier)|national (?:id|identifier)|identification|social security|ssn|"
    r"passport|driver'?s? licen[cs]e|tax id|password|passcode|pin code|"
    r"credentials|payment|credit card|debit card|card number|cvv|iban|bank details)\b"
)
BIRTH_REQUEST = re.compile(
    r"\b(?:tell|send|share|provide|enter|give|confirm|need|what|when|where)\b"
    r"[^.!?]{0,160}\b(?:birth(?:day|place| date| time| details)?|born|date of birth)\b"
    r"|\b(?:birth date|birth time|birthplace|date of birth)\s*[:?]"
)
HIGH_STAKES = re.compile(
    r"\b(medical|diagnos\w*|disease|illness|medication|pregnan\w*|fertil\w*|"
    r"death|die|dying|lifespan|suicid\w*|accident\w*|disaster\w*|criminal\w*|dangerous|"
    r"legal(?![ -]name)|lawsuit|court|invest\w*|stocks?|trading|trade|financial|bankrupt\w*|"
    r"divorce|break\s*up|miscarriage|infertil\w*|arrest\w*|jail|prison|"
    r"guaranteed (?:profit|return|outcome)|lose all (?:your|my) money|"
    r"(?:partner|spouse) will (?:leave|cheat)|relationship will (?:fail|end))\b"
)
CANCER_MEDICAL = re.compile(r"\b(get|have|develop|treat|cure|survive)\s+(?:\w+\s+){0,2}cancer\b")


def is_high_stakes(text: str) -> bool:
    value = normalize(text)
    return bool(HIGH_STAKES.search(value) or CANCER_MEDICAL.search(value))


def guard_reply(draft: str) -> str:
    """Validate free-form active replies only, never authorize collection or actions.

    Fixed replacement avoids extra provider calls and returns none of a blocked draft.
    This lexical baseline is not a multilingual/semantic classifier or PII scrubber.
    """
    value = normalize(draft)
    if PII.search(value) or BIRTH_REQUEST.search(value):
        return PRIVACY_REPLY
    if is_high_stakes(value):
        return SAFETY_REPLY
    return draft
