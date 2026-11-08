"""Bounded English memory intent/extraction, without model or persistence authority."""

import re
from dataclasses import dataclass, field
from typing import Literal

from oria_engine.domain.policy import normalize
from oria_engine.domain.temporal import HYPOTHETICAL, clauses

NO_REMEMBER = re.compile(r"\b(?:don['’]t|do not|never) (?:remember|save|store)\b", re.I)
RELATION = (
    "(?:girlfriend|boyfriend|wife|husband|partner|ex(?:-girlfriend|-boyfrie"
    "nd|-wife|-husband)?|mother|father|mom|dad|sister|brother|friend|cat|do"
    "g|pet|business|company|non-profit|house|car|phone)"
)
SUBJECT = re.compile(
    rf"\b(?:my|our) (?P<relation>{RELATION})(?:\s+(?P<name>[A-Z][\w'-]*(?: [A-Z][\w'-]*)?))?\b"
)
BLOCK_FACT = re.compile(
    "\\b(?:if|imagine|suppose|for "
    "example|hypothetically|maybe|perhaps|might|would|could|wish|not|never|"
    "didn't|did not|wasn't|was not)\\b",
    re.I,
)


@dataclass(frozen=True)
class Directive:
    action: Literal["read", "delete", "correct"]
    query: str = field(repr=False)


def directive(text: str) -> Directive | None:
    value = normalize(text).strip()
    if NO_REMEMBER.search(value):
        return None
    for pattern, action in (
        (r"^(?:please )?(?:forget|delete|remove)(?: (?:the )?saved)?\s+(.+)", "delete"),
        (r"^/forget\s+(.+)", "delete"),
        (r"^/(?:memories|memory)(?:\s+(.*))?$", "read"),
        (
            "^(?:what (?:do you|did you) (?:remember|know)(?: "
            "about)?|(?:show|list)(?: me)? (?:my |our |the )?(?:saved "
            ")?(?:memories|events|entities)|when (?:was|is|did))\\s*(.*)",
            "read",
        ),
        (
            "^(?:actually[, ]+|correction[: ,]+|(?:please "
            ")?(?:correct|update|change)\\s+|it was\\s+|that was\\s+)(.*)",
            "correct",
        ),
    ):
        match = re.match(pattern, value)
        if match:
            return Directive(action, (match[1] or "").strip(" .?!"))  # type: ignore[arg-type]
    return None


def privacy_control(text: str) -> bool:
    result = directive(text)
    return result is not None and result.action in {"read", "delete"}


def requested_follow_up(text: str) -> str | None:
    """Keep an explicit reading request alongside a locally saved disclosure."""
    from oria_engine.domain.temporal import BIRTH

    requests = []
    for start, end in clauses(text):
        clause = text[start:end].strip()
        if (
            not BIRTH.search(clause)
            and not extract_events(clause)
            and re.match(
                r"(?:can you|could you|I'd like|I would like|rate|tell me|how|what)\b", clause, re.I
            )
        ):
            requests.append(clause)
    return ". ".join(requests) or None


@dataclass(frozen=True, repr=False)
class EntityCandidate:
    label: str
    entity_type: Literal["person", "pet", "organization", "possession", "other"]
    relationship: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, repr=False)
class EventCandidate:
    event_type: str
    label: str
    participants: tuple[EntityCandidate, ...]
    start: int
    end: int


def entity_from(text: str) -> EntityCandidate | None:
    match = SUBJECT.search(text)
    if match is None:
        # Case-insensitive relation, but names remain explicitly capitalized.
        match = SUBJECT.search(re.sub(r"\b(My|Our)\b", lambda m: m[0].lower(), text))
    if match is None:
        return None
    relation, name = match["relation"].lower(), match["name"]
    if name is None:
        explicit = re.match(r"\s+([\w'-]+(?: [\w'-]+)?)\s+was born\b", text[match.end() :], re.I)
        if explicit:
            name = explicit[1]
    entity_type: Literal["person", "pet", "organization", "possession", "other"] = "person"
    if relation in {"cat", "dog", "pet"}:
        entity_type = "pet"
    elif relation in {"business", "company", "non-profit"}:
        entity_type = "organization"
    elif relation in {"house", "car", "phone"}:
        entity_type = "possession"
    label = f"my {relation}"
    return EntityCandidate(name or label, entity_type, relation, (label,) if name else ())


def extract_events(
    text: str,
    *,
    pronoun: EntityCandidate | None = None,
    known_entities: tuple[EntityCandidate, ...] = (),
) -> tuple[EventCandidate, ...]:
    """Only newly asserted bounded facts; questions/examples/negations are not facts."""
    if NO_REMEMBER.search(text) or HYPOTHETICAL.search(text):
        return ()
    found = []
    antecedent = pronoun
    for start, end in clauses(text):
        clause = text[start:end].strip()
        value = normalize(clause)
        if text[end : end + 1] == "?":
            continue
        # A question about an event is not a disclosure of that event.
        if BLOCK_FACT.search(value) or re.match(
            r"(?:when|what|how|did|was|is|can|do|tell me)\b", value
        ):
            continue
        if clause.startswith(('"', "“", "'", "`", ">")):
            continue
        subject = entity_from(clause)
        if subject is None:
            named = [
                entity
                for entity in known_entities
                if any(
                    re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", clause, re.I)
                    for label in (entity.label, *entity.aliases)
                )
            ]
            if len(named) == 1:
                subject = named[0]
        if subject:
            antecedent = subject
        event_type = label = None
        participants: tuple[EntityCandidate, ...] = ()
        if re.search(
            r"\b(?:I|we) (?:got )?married\b|"
            r"\b(?:our|my) wedding (?:was|is|happened|took place|on)\b",
            clause,
            re.I,
        ):
            event_type, label = "wedding", "our wedding"
            if subject is not None:
                participants = (subject,)
        elif re.search(
            "\\b(?:my|our) parents (?:got |were )?divorced\\b|\\bmy parents['’]? "
            "divorce (?:was|happened|on)\\b",
            clause,
            re.I,
        ):
            event_type, label = "divorce", "my parents' divorce"
            participants = (
                EntityCandidate("my mother", "person", "mother"),
                EntityCandidate("my father", "person", "father"),
            )
        elif re.search(r"\b(?:was born|birthday (?:is|was)|birth date (?:is|was))\b", clause, re.I):
            if (
                re.search(r"\bI was born\b|\bmy (?:birthday|birth date)\b", clause, re.I)
                and subject is None
            ):
                continue  # One canonical own-birth profile, edited explicitly.
            if subject is None and re.search(r"\b(?:her|his|their|she|he|they)\b", clause, re.I):
                subject = antecedent
            if subject is not None:
                event_type, label, participants = "birth", f"{subject.label}'s birth", (subject,)
        elif re.search(r"\b(?:I|we) (?:bought|purchased)\b", clause, re.I):
            event_type, label = "purchase", "purchase"
            if subject is None:
                obj = re.search(r"\b(?:a|the) (house|car|phone)\b", value)
                subject = entity_from(f"my {obj[1]}") if obj else None
            if subject:
                label, participants = f"{subject.label} purchase", (subject,)
        elif re.search(r"\b(?:I|we) (?:adopted|got)\b", clause, re.I):
            if subject is None:
                obj = re.search(r"\b(?:a|the) (cat|dog|pet)\b", value)
                subject = entity_from(f"my {obj[1]}") if obj else None
            if subject and subject.entity_type == "pet":
                event_type, label, participants = (
                    "adoption",
                    f"{subject.label} adoption",
                    (subject,),
                )
        elif re.search(r"\b(?:I|we) changed (?:my |our )?job\b", clause, re.I):
            event_type, label = "job change", "my job change"
        elif re.search(r"\b(?:I|we) founded\b", clause, re.I):
            event_type, label = "founding", "business founding"
            if subject:
                label, participants = f"{subject.label} founding", (subject,)
        elif re.match(r"(?:please )?remember (?:that )?", value):
            event_type = "life event"
            label = re.sub(r"^(?:please )?remember (?:that )?", "", clause, flags=re.I)[:160]
            if subject:
                participants = (subject,)
        if event_type and label:
            found.append(EventCandidate(event_type, label, participants, start, end))
    return tuple(found)
