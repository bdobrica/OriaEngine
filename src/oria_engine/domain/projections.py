"""Bounded projection text and traditional themes; no raw calculation inputs."""

import re

from oria_engine.db.knowledge import SavedRecord
from oria_engine.knowledge.contracts import ContextProjection, EntityRecord, Salience
from oria_engine.privacy.messages import private_active_input

# Traditional retrieval themes; no measured houses or astrological causation.
THEMES: dict[int, str] = {
    1: r"identity|self.image|appearance|style|vitality",
    2: r"money|finances|values|possessions|earnings|self.worth",
    3: r"communication|siblings|neighbors|learning|local travel",
    4: r"home|house|parents|family|roots|wedding|divorce",
    5: r"creativity|romance|hobbies|children|joy|dating",
    6: r"health|routines|daily work|job|cat|dog|pet|adoption",
    7: (
        r"partnership|partner|relationships?|marriage|wedding|girlfriend|boyfriend|"
        r"wife|husband|divorce"
    ),
    8: r"intimacy|inheritance|joint finances|shared resources|transformation|wedding",
    9: r"philosophy|university|education|travel|beliefs|religion|publishing|law",
    10: r"career|job|business|founding|ambition|reputation|legacy",
    11: r"friends|networks|community|groups|aspirations|nonprofit",
    12: r"dreams|subconscious|isolation|secrets|endings|spirituality",
}


def themes(text: str) -> tuple[int, ...]:
    return tuple(
        h for h, pattern in THEMES.items() if re.search(r"\b(?:" + pattern + r")\b", text, re.I)
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
