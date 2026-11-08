"""Bounded projection text and traditional themes; no raw calculation inputs."""

import re

from oria_engine.db.knowledge import SavedRecord
from oria_engine.knowledge.contracts import ContextProjection, EntityRecord, Salience
from oria_engine.privacy.messages import private_active_input

# Traditional retrieval themes; no measured houses or astrological causation.
THEMES: dict[int, str] = {
    1: r"identity|self.image|appearance|style|vitality|first impressions|ascendant",
    2: r"money|finances|values|possessions|earnings|self.worth|personal resources|material comfort",
    3: r"communication|siblings|neighbors|neighbours|learning|local travel|early education",
    4: r"home|house|parents|family|roots|wedding|divorce|emotional security|imum coeli",
    5: r"creativity|romance|hobbies|children|joy|dating|play|self.expression",
    6: r"health|routines|daily work|job|cat|dog|pets?|adoption|habits|service|organization",
    7: (
        r"partnership|partner|relationships?|marriage|wedding|girlfriend|boyfriend|"
        r"wife|husband|divorce|alliances|contracts|descendant|cooperation"
    ),
    8: r"intimacy|inheritance|joint finances|shared resources|transformation|wedding|taxes|rebirth",
    9: r"philosophy|university|education|travel|beliefs|religion|publishing|law",
    10: r"career|job|business|founding|ambition|reputation|legacy|public status|midheaven|vocation",
    11: r"friends|networks|community|groups|aspirations|non.?profit|collaboration|humanitarian",
    12: (
        r"dreams|subconscious|unconscious|isolation|secrets|endings?|spirituality|"
        r"mental health|karma"
    ),
}


def themes(text: str) -> tuple[int, ...]:
    numbered_house = r"\b(?:(1[0-2]|[1-9])(?:st|nd|rd|th)?\s+house|house\s+(1[0-2]|[1-9]))\b"
    explicit = {int(m[1] or m[2]) for m in re.finditer(numbered_house, text, re.I)}
    topic_text = re.sub(numbered_house, "", text, flags=re.I)
    return tuple(
        h
        for h, pattern in THEMES.items()
        if h in explicit or re.search(r"\b(?:" + pattern + r")\b", topic_text, re.I)
    )


def safe_text(text: str) -> bool:
    # Deliberately conservative: summaries with any numbers/clock/date notation,
    # birth-bearing language or apparent credentials are never remembered.
    return not (
        re.search(
            r"\d|\b(?:born|birthday|birthplace|january|february|march|april|may|june|july|august|september|october|november|december)\b",
            text,
            re.I,
        )
        or private_active_input(text)
        or len(text) > 2048
    )


def canonical_projection(saved: SavedRecord) -> ContextProjection:
    r = saved.record
    if isinstance(r, EntityRecord):
        label = r.label if safe_text(r.label) else r.entity_type
        relation = r.relationship_to_user
        summary = f"The user described {label} ({r.entity_type})."
        if relation and safe_text(relation):
            summary += f" Relationship to the user: {relation}."
        topic_text = summary
    else:
        # Event descriptions and all temporal/place/provenance values stay local.
        kind = (
            r.event_type
            if r.event_type
            in {"wedding", "birth", "divorce", "purchase", "adoption", "job change", "founding"}
            else "life event"
        )
        label, summary, topic_text = kind, f"The user described a {kind} event.", kind
    return ContextProjection(
        record=saved.ref,
        label=label,
        summary=summary,
        knowledge_kind="user_statement",
        sources=(saved.ref,),
        house_themes=themes(topic_text),
        salience=Salience(score=0.5, basis="inferred", method_version="linked-salience-1"),
    )
