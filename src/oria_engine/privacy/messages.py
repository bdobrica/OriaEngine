"""Prepare active chat without treating volunteered PII as a refusal category."""

import re

from oria_engine.domain.policy import normalize

BIRTH_INPUT = re.compile(r"\b(?:born|birthday|birthplace|birth date|birth time|date of birth)\b")
SECRET = re.compile(
    r"\b(?:password|passcode|api[ _-]?key|access[ _-]?token|secret[ _-]?key|cvv|pin code)"
    r"\s*(?:is\s+|[=:]\s*)\S+|\bsk-[a-z0-9_-]{12,}\b"
)


def private_active_input(text: str, *, resolved_clock: bool = False) -> bool:
    """Hold obvious account secrets locally; ordinary PII and clock text are allowed.

    resolved_clock remains accepted for existing internal callers. It grants no
    permission to collect fields. This bounded detector cannot identify every secret.
    """
    return bool(SECRET.search(normalize(text)))


def prepare_active_input(text: str) -> str:
    """Withhold birth-bearing messages under the existing v1 context boundary.

    This coarse fallback preserves a supported conversational goal, without sending
    raw birth inputs, guessing their subject or pretending to extract/store events.
    Slice 2 replaces it with typed temporal roles and richer local extraction.
    The result is idempotent and carries no user-supplied values from such a message.
    """
    value = normalize(text)
    if not BIRTH_INPUT.search(value):
        return text
    if re.search(
        r"\b(?:compatibility|compatible|synastry|girlfriend|boyfriend|wife|husband|partner)\b",
        value,
    ):
        question = (
            "I'd like a compatibility rating."
            if re.search(r"\b(?:rate|rating|score)\b", value)
            else "I'd like to discuss my relationship."
        )
    else:
        question = "I'd like to discuss my personal context alongside my chart."
    return question + " [Birth inputs held locally; no additional calculation was performed.]"
