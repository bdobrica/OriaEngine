"""Prepare active chat without treating volunteered PII as a refusal category."""

import re

from oria_engine.domain.policy import normalize
from oria_engine.domain.temporal import BIRTH, clauses

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


def held_birth_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Include obvious multi-sentence continuations; labels need not repeat 'born'."""
    held = []
    birth_context = False
    for start, end in clauses(text):
        clause = text[start:end].strip()
        normalized = normalize(clause)
        if BIRTH.search(normalized):
            birth_context = True
            held.append((start, end))
            continue
        if birth_context and re.match(
            r"(?:\d|at\b|in\b|on\b|time\b|date\b|place\b|city\b|coordinates\b)", normalized
        ):
            held.append((start, end))
            continue
        if clause:
            birth_context = False
    return tuple(held)


def prepare_active_input(text: str) -> str:
    """Hold birth-bearing clauses locally while preserving other conversational goals.

    A clause may contain unparsed birthplaces/times as well as recognized dates, so
    removing only date spans would leak inputs. This bounded English preparation
    keeps other clauses and never forwards a typed birth candidate to the model.
    """
    value = normalize(text)
    if not BIRTH_INPUT.search(value):
        return text
    held = held_birth_spans(text)
    kept = [text[start:end].strip() for start, end in clauses(text) if (start, end) not in held]
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
    remaining = ". ".join(part for part in kept if part)
    marker = " [Birth inputs held locally; no additional calculation was performed.]"
    return (remaining or question)[: 4096 - len(marker)] + marker
