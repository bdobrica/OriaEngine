"""Owner-scoped linked reading preparation. No model-selected sources or tools."""

import asyncio
import re
from dataclasses import dataclass
from itertools import combinations
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.astrology.client import AstrologyClient, AstrologyUnavailable
from oria_engine.astrology.contracts import WireModel
from oria_engine.astrology.linked import (
    ChartFacts,
    ChartInput,
    CrossAspect,
    LinkedMetadata,
    Overlay,
    SynastryRequest,
    SynastryResult,
    validate_chart,
)
from oria_engine.db.birth_profiles import BirthProfileRepository
from oria_engine.db.knowledge import KnowledgeRepository, SavedRecord
from oria_engine.db.temporal import PendingTemporal, TemporalRepository
from oria_engine.domain.birth_time import birth_zone, utc_candidates
from oria_engine.domain.knowledge import names, supplied_place
from oria_engine.domain.memory import NO_REMEMBER, entity_from
from oria_engine.domain.places import PlaceResolutionUnavailable, PlaceResolver, TooManyPlaces
from oria_engine.domain.projections import themes
from oria_engine.domain.temporal import TemporalMention, clauses
from oria_engine.domain.temporal_dialogue import TemporalDialogue
from oria_engine.knowledge.contracts import (
    CalendarDate,
    EntityRecord,
    EventRecord,
    House,
    Instant,
    LocalDateTime,
    RecordRef,
    TemporalEvidence,
)
from oria_engine.persona.houses import HOUSE_DOMAINS
from oria_engine.privacy.encryption import ProfileEncryption

Role = Literal["self", "other", "event"]
COMPATIBILITY = re.compile(r"\b(?:compatib(?:ility|le)|synastry)\b", re.I)
EVENT_READING = re.compile(
    r"\b(?:reading|read|interpret\w*|chart|astrolog\w*|themes|insights?)\b", re.I
)
EVENT_WORD = re.compile(
    r"\b(?:wedding|marriage|divorce|purchase|adoption|job change|founding|business|"
    r"birthday|girlfriend|boyfriend|wife|husband|partner|event)\b",
    re.I,
)


def wants_linked(text: str) -> bool:
    if COMPATIBILITY.search(text):
        return True
    return any(
        EVENT_READING.search(clause := text[start:end])
        and (
            EVENT_WORD.search(clause)
            or re.search(r"\b(?:her|his|their|its) (?:birth )?chart\b", clause, re.I)
        )
        for start, end in clauses(text)
    )


class ReadingChart(WireModel):
    role: Role
    convention: Literal["birth", "event"] = "birth"
    facts: ChartFacts


class ReadingComparison(WireModel):
    a: Role
    b: Role
    aspects: tuple[CrossAspect, ...] = Field(max_length=100)
    overlays: tuple[Overlay, ...] = Field(max_length=20)


class InterpretiveRating(WireModel):
    score: float = Field(ge=1, le=10, allow_inf_nan=False)
    scale: Literal[10] = 10
    method: Literal["oria-reflection-rating-1"] = "oria-reflection-rating-1"


def requested_rating(text: str, comparisons: list[ReadingComparison]) -> InterpretiveRating | None:
    if not re.search(r"\b(?:rate|rating|score)\b", text, re.I):
        return None
    aspects = [a for c in comparisons if c.a == "self" and c.b == "other" for a in c.aspects]
    if not aspects:
        return None
    weights = {
        "trine": 1.0,
        "sextile": 0.75,
        "conjunction": 0.25,
        "square": -1.0,
        "opposition": -0.75,
    }
    total = sum((7 - a.orb) for a in aspects)
    balance = sum(weights[a.name] * (7 - a.orb) for a in aspects) / total
    return InterpretiveRating(score=round(5 + 3 * balance, 1))


class LinkedReading(WireModel):
    contract_version: Literal[1] = 1
    kind: Literal["compatibility", "event_reading"]
    charts: tuple[ReadingChart, ...] = Field(min_length=1, max_length=3)
    comparisons: tuple[ReadingComparison, ...] = Field(default=(), max_length=3)
    sources: tuple[RecordRef, ...] = Field(default=(), max_length=32)
    house_themes: tuple[House, ...] = Field(default=(), max_length=12)
    rating: InterpretiveRating | None = None
    metadata: LinkedMetadata = Field(default_factory=LinkedMetadata)


@dataclass(frozen=True, repr=False)
class ReadingPreparation:
    facts: LinkedReading | None = None
    question: str | None = None
    date_template: str | None = None
    selected_record: RecordRef | None = None


async def hold_date_question(
    repository: TemporalRepository,
    user_id: UUID,
    consent_id: UUID,
    dialogue: TemporalDialogue,
    preparation: ReadingPreparation,
) -> None:
    """Reuse the encrypted, expiring date-answer flow without a new memory lane."""
    template = preparation.date_template
    if template is None or NO_REMEMBER.search(dialogue.text):
        return
    pending_text = dialogue.text + ". " + template.format(date="DATE_NEEDED")
    if len(pending_text) > 4096:
        return
    start = pending_text.rindex("DATE_NEEDED")
    await repository.save(
        user_id,
        PendingTemporal(
            consent_id=consent_id,
            text=pending_text,
            reference_time_utc=dialogue.reference,
            timezone=dialogue.timezone,
            timezone_source=dialogue.timezone_source,
            source_update_id=dialogue.source_update_id,
            operation_source=dialogue.operation_source,
            selected_record=preparation.selected_record,
            unresolved=TemporalMention(
                start=start,
                end=start + len("DATE_NEEDED"),
                role="birth_input" if "birthday" in template else "life_event",
                evidence=TemporalEvidence(
                    expression="DATE_NEEDED",
                    reference_time_utc=dialogue.reference,
                    resolution_version="english-gregorian-2",
                ),
                issue="date",
            ),
        ),
    )


async def event_input(event: EventRecord, resolver: PlaceResolver) -> ChartInput | None:
    evidence = event.temporal
    value = evidence.value if evidence else None
    if not isinstance(value, (CalendarDate, Instant, LocalDateTime)):
        return None
    latitude: float | None = None
    longitude: float | None = None
    place = None
    if event.place and "," in event.place:
        city, country = event.place.rsplit(",", 1)
        try:
            choices = await resolver.resolve(city.strip(), country.strip())
            if len(choices) == 1:
                place = choices[0]
                latitude, longitude = place.latitude, place.longitude
        except (PlaceResolutionUnavailable, TooManyPlaces):
            pass  # Positions remain useful when a place cannot be selected safely.
    approximate = getattr(value, "approximate", False)
    if isinstance(value, CalendarDate):
        if not 1800 <= value.value.year <= 2399:
            return None
        return ChartInput(
            accuracy="unknown",
            calendar_date=value.value,
            date_approximate=value.approximate,
            latitude=latitude,
            longitude=longitude,
        )
    assert evidence is not None
    clock = value.value
    # A current timezone preference is not a historical event/birth timezone.
    if isinstance(value, Instant) and evidence.timezone:
        clock = clock.astimezone(birth_zone(evidence.timezone)).replace(tzinfo=None)
    if evidence.timezone_source == "explicit_event" and isinstance(value, Instant):
        if not 1800 <= value.value.year <= 2399:
            return None
        return ChartInput(
            accuracy="approximate" if approximate else "exact",
            timestamp_utc=value.value,
            latitude=latitude,
            longitude=longitude,
        )
    if place is not None:
        try:
            candidates = utc_candidates(clock.date(), clock.time(), place.timezone)
        except ValueError:
            candidates = ()
        if len(candidates) == 1:
            if not 1800 <= candidates[0].year <= 2399:
                return None
            return ChartInput(
                accuracy="approximate" if approximate else "exact",
                timestamp_utc=candidates[0],
                latitude=latitude,
                longitude=longitude,
            )
    # Preserve the supplied local date; do not invent a timezone or select a DST fold.
    if not 1800 <= clock.year <= 2399:
        return None
    return ChartInput(
        accuracy="unknown",
        calendar_date=clock.date(),
        date_approximate=approximate,
        latitude=latitude,
        longitude=longitude,
    )


def _mentions(text: str, saved: SavedRecord) -> bool:
    text = re.sub(r"\b(?:marriage|married)\b", "wedding", text, flags=re.I)
    text = re.sub(r"\bfoundation\b", "founding", text, flags=re.I)
    return any(
        re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", text, re.I)
        for label in names(saved.record)
    )


async def prepare_linked_reading(
    session: AsyncSession,
    user_id: UUID,
    *,
    encryption: ProfileEncryption,
    policy_version: str,
    client: AstrologyClient,
    resolver: PlaceResolver,
    dialogue: TemporalDialogue,
) -> ReadingPreparation:
    text = dialogue.text
    compatibility = bool(COMPATIBILITY.search(text))
    repository = KnowledgeRepository(session, encryption, policy_version)
    await repository.lock(user_id, write=True)
    records = await repository.list(user_id)
    entities = [s for s in records if isinstance(s.record, EntityRecord) and _mentions(text, s)]
    if len(entities) > 1:
        return ReadingPreparation(question="Which person should I compare your chart with?")
    progress = await repository.progress(user_id)
    if not entities and re.search(r"\b(?:her|his|their|she|he|they|us|our|it|that)\b", text, re.I):
        focus_ids = {r.id for r in progress.focus} if progress else set()
        entities = [
            s for s in records if s.ref.id in focus_ids and isinstance(s.record, EntityRecord)
        ]
    entity_ids = {s.ref.id for s in entities}
    candidate_entity = entity_from(text)
    subject = (
        names(entities[0].record)[0]
        if entities
        else (candidate_entity.label if candidate_entity is not None else "the other person")
    )
    births = [
        s
        for s in records
        if isinstance(s.record, EventRecord)
        and s.record.event_type == "birth"
        and any(p.entity_id in entity_ids for p in s.record.participants)
    ]
    entity_event = (
        compatibility
        and not births
        and len(entities) == 1
        and isinstance(entities[0].record, EntityRecord)
        and entities[0].record.entity_type != "person"
    )
    events = [
        s
        for s in records
        if isinstance(s.record, EventRecord)
        and s.record.event_type != "birth"
        and (
            _mentions(text, s)
            or s.ref == dialogue.selected_record
            or (not compatibility or entity_event)
            and any(p.entity_id in entity_ids for p in s.record.participants)
        )
    ]
    years = {int(year) for year in re.findall(r"\b\d{4}\b", text)}
    if len(events) > 1 and len(years) == 1:
        events = [
            s
            for s in events
            if isinstance(s.record, EventRecord)
            and s.record.temporal is not None
            and isinstance(s.record.temporal.value, (CalendarDate, Instant, LocalDateTime))
            and s.record.temporal.value.value.year in years
        ]
    if len(births) > 1 or len(events) > 1:
        return ReadingPreparation(
            question="Which saved event do you mean? Please name its date or participants."
        )
    if any(s.needs_review for s in (*births, *events)):
        return ReadingPreparation(
            question=(
                "That event's date needs confirmation after an anchor changed. What is its date?"
            )
        )
    # A supplied input can be calculated without learning it (including opt-out).
    # It never acquires a canonical reference merely by appearing in a question.
    transient: EventRecord | None = None
    if not births and not events or NO_REMEMBER.search(text):
        candidates = [
            m
            for m in dialogue.analysis.mentions
            if m.role in {"birth_input", "life_event", "target", "context"}
            and not m.issue
            and not (
                m.role == "birth_input"
                and any(
                    start <= m.start < end
                    and re.search(
                        r"\b(?:I was born|my (?:birthday|birth date|date of birth))\b",
                        text[start:end],
                        re.I,
                    )
                    for start, end in clauses(text)
                )
            )
        ]
        if len(candidates) == 1 and (entity_from(text) is not None or EVENT_WORD.search(text)):
            m = candidates[0]
            transient = EventRecord(
                id=uuid4(),
                revision=1,
                event_type="birth" if m.role == "birth_input" else "life event",
                description="supplied calculation input",
                temporal=m.evidence,
                place=supplied_place(text),
                source_message_id=uuid4(),
            )
            if NO_REMEMBER.search(text):
                if transient.event_type == "birth":
                    births = []
                else:
                    events = []
    if not births and not events and transient is None:
        return ReadingPreparation(
            question=(
                "What is your partner's birth date? A date is enough to start; "
                "time and city are optional."
                if compatibility
                else "Which event should I read, and what date did it happen?"
            ),
            date_template=f"{subject}'s birthday is {{date}}" if compatibility else None,
        )
    profile = await BirthProfileRepository(session, encryption, policy_version=policy_version).get(
        user_id
    )
    assert profile is not None  # Active flow requires a confirmed profile.
    own = await repository.own_birth(user_id)
    assert own is not None
    instant = profile.utc_instant()
    inputs: dict[Role, ChartInput] = {
        "self": ChartInput(
            accuracy=profile.birth_time_accuracy,
            timestamp_utc=instant,
            calendar_date=profile.birth_date if instant is None else None,
            latitude=profile.birth_place.latitude,
            longitude=profile.birth_place.longitude,
        )
    }
    sources = {own.ref.id: own.ref}
    conventions: dict[Role, Literal["birth", "event"]] = {"self": "birth"}
    for saved in (*births, *events):
        assert isinstance(saved.record, EventRecord)
        chart_input = await event_input(saved.record, resolver)
        if chart_input is None:
            return ReadingPreparation(
                question=(
                    "I need a complete date within 1800–2399 for this calculation. "
                    "We can still discuss the event's themes with partial information."
                ),
                date_template=(
                    f"{subject}'s birthday is {{date}}"
                    if saved.record.event_type == "birth"
                    else f"{saved.record.description} was {{date}}"
                ),
                selected_record=saved.ref,
            )
        role: Role = "other" if saved.record.event_type == "birth" or entity_event else "event"
        inputs[role] = chart_input
        conventions[role] = "birth" if saved.record.event_type == "birth" else "event"
        sources[saved.ref.id] = saved.ref
        for participant in saved.record.participants:
            for entity in records:
                if entity.ref.id == participant.entity_id:
                    sources[entity.ref.id] = entity.ref
    if transient is not None:
        chart_input = await event_input(transient, resolver)
        if chart_input is None:
            return ReadingPreparation(
                question=(
                    "I need a complete date within 1800–2399 for this calculation. "
                    "We can still discuss the event's themes with partial information."
                )
            )
        role = "other" if transient.event_type == "birth" or entity_event else "event"
        inputs[role] = chart_input
        conventions[role] = "birth" if transient.event_type == "birth" else "event"
    if compatibility and "other" not in inputs:
        return ReadingPreparation(
            question="What is your partner's birth date? Time and city are optional."
        )
    if len(sources) > 32:
        return ReadingPreparation(question="Which participants should this reading focus on?")
    charts: dict[Role, ChartFacts] = {}
    comparisons = []
    try:
        async with asyncio.timeout(20):
            for a, b in combinations(inputs, 2):
                request = SynastryRequest(
                    calculation_id=uuid4(), chart_a=inputs[a], chart_b=inputs[b]
                )
                result = SynastryResult.model_validate(await client.calculate_synastry(request))
                if result.calculation_id != request.calculation_id:
                    raise ValueError()
                for role, facts in ((a, result.chart_a), (b, result.chart_b)):
                    validate_chart(inputs[role], facts)
                    if role in charts and charts[role] != facts:
                        raise ValueError()
                    charts[role] = facts
                comparisons.append(
                    ReadingComparison(a=a, b=b, aspects=result.aspects, overlays=result.overlays)
                )
    except Exception:
        raise AstrologyUnavailable("Linked calculation temporarily unavailable") from None
    topics = set(themes(text))
    for saved in (*births, *events):
        assert isinstance(saved.record, EventRecord)
        topics.update(themes(saved.record.event_type))
    topics.update(o.house for c in comparisons for o in c.overlays)
    return ReadingPreparation(
        facts=LinkedReading(
            kind="compatibility" if compatibility else "event_reading",
            charts=tuple(
                ReadingChart(role=role, convention=conventions[role], facts=facts)
                for role, facts in charts.items()
            ),
            comparisons=tuple(comparisons),
            sources=tuple(sources.values()),
            house_themes=tuple(sorted(topics)),
            rating=requested_rating(text, comparisons) if compatibility else None,
        )
    )


def interpretation_summary(facts: LinkedReading) -> str:
    """Minimal qualitative recollection, no birth input, score or stale chart numbers."""
    features = [
        f"{a.body_a.title()}–{a.body_b.title()} {a.name}"
        for c in facts.comparisons
        for a in sorted(c.aspects, key=lambda a: a.orb)[:2]
    ][:6]
    return (
        "A linked "
        + ("relationship" if facts.kind == "compatibility" else "event")
        + " reading considered "
        + (
            ", ".join(features)
            if features
            else "the supplied charts without major cross-chart aspects"
        )
        + ". These were interpretive themes, to revisit using current calculations."
    )


def render_linked(facts: LinkedReading) -> str:
    """Factual local fallback when linked source delivery or generation is unavailable."""
    lines = []
    if facts.rating is not None:
        lines.append(
            f"My interpretive compatibility rating: {facts.rating.score:g}/10, "
            "balancing the supplied harmonious and challenging aspects."
        )
    if any(c.facts.precision == "date_sample" for c in facts.charts):
        lines.append(
            "For inputs without a resolved time I used a noon-UTC sample; those positions "
            "and links can change with the actual time. Houses are unavailable for those inputs."
        )
    if any(c.facts.precision == "approximate" for c in facts.charts):
        lines.append("The supplied approximate times make placements and overlays approximate too.")
    if any("approximate_date" in c.facts.reasons for c in facts.charts):
        lines.append("An approximate date makes its sampled positions uncertain too.")
    chart_names = {"self": "Your chart", "other": "The other chart", "event": "The event chart"}
    possessive = {"self": "Your", "other": "The other chart's", "event": "The event chart's"}
    for c in facts.comparisons:
        lines.append(f"{chart_names[c.a]} alongside {chart_names[c.b].lower()}:")
        for a in sorted(c.aspects, key=lambda a: a.orb)[:3]:
            theme = {
                "trine": "an easy flow to explore",
                "sextile": "cooperation to develop",
                "square": "different needs to work through",
                "opposition": "a balance of contrasting needs",
                "conjunction": "a concentrated shared theme",
            }[a.name]
            lines.append(
                f"{a.body_a.title()}–{a.body_b.title()} {a.name} ({a.orb:.2f}°): "
                f"traditionally, {theme}."
            )
        if not c.aspects:
            lines.append("No major cross-chart aspects within the configured six-degree orb.")
        for overlay in [o for o in c.overlays if o.body in {"sun", "moon", "venus"}][:3]:
            source, target = (c.a, c.b) if overlay.direction == "a_in_b" else (c.b, c.a)
            precision = {"exact": "", "approximate": " (approximate)", "date_sample": " (sampled)"}[
                overlay.precision
            ]
            lines.append(
                f"{possessive[source]} {overlay.body.title()} in "
                f"{possessive[target].lower()} house {overlay.house}"
                f"{precision}: {HOUSE_DOMAINS[overlay.house].lower()} themes."
            )
    if not any(c.overlays for c in facts.comparisons) and facts.house_themes:
        lines.append(
            "Traditional topics to explore: "
            + ", ".join(HOUSE_DOMAINS[h].lower() for h in facts.house_themes[:4])
            + "."
        )
    return "\n".join(lines)[:3900]
