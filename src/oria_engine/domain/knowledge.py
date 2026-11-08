"""Application-owned conversational CRUD, kept local until remote lifecycle support.

Extraction is bounded English. Typed candidates cannot choose an owner or execute
model-suggested writes. The caller commits changes and the reply atomically.
"""

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.db.birth_profiles import BirthProfileRepository
from oria_engine.db.knowledge import (
    KnowledgeConflict,
    KnowledgeRepository,
    MemoryProgress,
    SavedRecord,
)
from oria_engine.domain.birth_time import birth_zone
from oria_engine.domain.channel import ChannelMessage
from oria_engine.domain.memory import (
    NO_REMEMBER,
    Directive,
    EntityCandidate,
    directive,
    entity_from,
    extract_events,
    requested_follow_up,
)
from oria_engine.domain.policy import is_harmful_request, normalize
from oria_engine.domain.temporal import MONTHS, EventAnchor
from oria_engine.domain.temporal_dialogue import TemporalDialogue
from oria_engine.knowledge.contracts import (
    CalendarDate,
    EntityRecord,
    EventRecord,
    Instant,
    LocalDateTime,
    PartialDate,
    Participant,
    RecordRef,
    TemporalEvidence,
)
from oria_engine.privacy.encryption import ProfileEncryption
from oria_engine.privacy.messages import private_active_input


@dataclass(frozen=True, repr=False)
class MemoryTurn:
    message: ChannelMessage = field(repr=False)
    selected: RecordRef | None = None
    force_new: bool = False
    cascade_confirmed: bool = False
    cascade_refs: tuple[RecordRef, ...] = ()
    source: UUID | None = None
    timezone: str | None = None
    timezone_source: Literal["explicit_event", "current_preference"] = "current_preference"
    reply: str | None = field(default=None, repr=False)


def source_id(user_id: UUID, message: ChannelMessage) -> UUID:
    # Stable non-PII provenance/deduplication key, also for direct flow callers.
    return uuid5(
        NAMESPACE_URL, f"oria:knowledge:{user_id}:{message.provider}:{message.provider_update_id}"
    )


def names(record: EntityRecord | EventRecord) -> tuple[str, ...]:
    if isinstance(record, EntityRecord):
        return (record.label, *record.aliases)
    return (record.description, record.event_type)


def matches(query: str, saved: SavedRecord, extra: tuple[str, ...] = ()) -> bool:
    query = normalize(query).strip(" .?!")
    query = re.sub(
        r"\b(?:the|about|date|on|in|to|saved|event|events|memory|memories|please|do you|"
        r"remember|know|we|did|get|got|is|was|were|i)\b",
        " ",
        query,
    )
    query = re.sub(r"['’]s\b", "", query)
    query = re.sub(r"\s+", " ", query).strip()
    if not query or query in {"everything", "all", "me", "my", "our"}:
        return True
    aliases = " ".join(normalize(n) for n in (*names(saved.record), *extra))
    aliases = re.sub(r"['’]s\b", "", aliases)
    tokens = set(re.findall(r"[\w'-]+", query)) - {"my", "our", "that", "this"}
    synonyms = {
        "birthday": "birth",
        "born": "birth",
        "married": "wedding",
        "marry": "wedding",
        "marriage": "wedding",
        "buy": "purchase",
        "bought": "purchase",
    }
    tokens = {synonyms.get(token, token) for token in tokens}
    alias_tokens = {synonyms.get(token, token) for token in re.findall(r"[\w'-]+", aliases)}
    return bool(tokens) and tokens.issubset(alias_tokens)


def date_text(evidence: TemporalEvidence | None) -> str:
    if evidence is None or evidence.value is None:
        return "date not known"
    value = evidence.value
    if isinstance(value, CalendarDate):
        text = value.value.isoformat()
    elif isinstance(value, (Instant, LocalDateTime)):
        clock = value.value
        if isinstance(value, Instant) and evidence.timezone:
            clock = clock.astimezone(birth_zone(evidence.timezone))
        text = clock.isoformat() + (
            f" ({evidence.timezone})" if evidence.timezone else " (timezone unknown)"
        )
    elif isinstance(value, PartialDate):
        text = "-".join(
            f"{n:02d}" if n is not None else "?" for n in (value.year, value.month, value.day)
        )
    else:
        text = value.model_dump_json()
    if getattr(value, "approximate", False):
        text = "approximately " + text
    return text


def supplied_place(clause: str) -> str | None:
    """Keep an explicit place label; do not geocode or infer coordinates/timezone."""
    for match in re.finditer(r"\bin\s+([A-Z][A-Za-zÀ-ÿ' -]*(?:,\s*[A-Z][A-Za-zÀ-ÿ' -]*)?)", clause):
        label = re.split(r"\s+(?:on|at|in|and|with)\s+", match[1], maxsplit=1)[0].strip(" ,")
        if label.casefold() not in MONTHS and clause[match.end() : match.end() + 1] != "/":
            return label[:160] or None
    return None


def describe(saved: SavedRecord) -> str:
    record = saved.record
    if isinstance(record, EntityRecord):
        aliases = f"; also {', '.join(record.aliases)}" if record.aliases else ""
        return (
            f"{record.label} ({record.entity_type}; "
            f"{record.relationship_to_user or 'relationship not set'}{aliases})"
        )
    if saved.needs_review:
        return f"{record.description}: date needs confirmation because a referenced event changed"
    return f"{record.description}: {date_text(record.temporal)}" + (
        f"; {record.place}" if record.place else ""
    )


def bounded_reply(prefix: str, records: tuple[SavedRecord, ...]) -> str:
    lines = [prefix]
    for saved in records:
        line = "\n" + describe(saved)
        if len(("".join(lines) + line).encode("utf-16-le")) // 2 > 3800:
            lines.append("\nThere are more records; ask about a particular person or event.")
            break
        lines.append(line)
    return "".join(lines)


def cap_reply(text: str) -> str:
    encoded = text.encode("utf-16-le")
    if len(encoded) <= 7900:
        return text
    return (
        encoded[:7500].decode("utf-16-le", errors="ignore")
        + "\nUse /memories for more saved details."
    )


class MemoryQuestion(Exception):
    def __init__(self, choices: tuple[SavedRecord, ...], question: str):
        super().__init__("Memory selection required")
        self.choices, self.question = choices, question


class KnowledgeConversation:
    def __init__(self, session: AsyncSession, encryption: ProfileEncryption, policy_version: str):
        self.session, self.encryption, self.policy_version = session, encryption, policy_version
        self.repository = KnowledgeRepository(session, encryption, policy_version)

    def _matches(self, query: str, saved: SavedRecord, records: tuple[SavedRecord, ...]) -> bool:
        extra: tuple[str, ...] = ()
        if isinstance(saved.record, EventRecord):
            ids = {p.entity_id for p in saved.record.participants}
            extra = tuple(
                n
                for entity in records
                if isinstance(entity.record, EntityRecord) and entity.record.id in ids
                for n in names(entity.record)
            )
            value = saved.record.temporal.value if saved.record.temporal else None
            year = (
                value.value.year
                if isinstance(value, (CalendarDate, Instant, LocalDateTime))
                else value.year
                if isinstance(value, PartialDate)
                else None
            )
            if year is not None:
                extra = (*extra, str(year))
        return matches(query, saved, extra)

    async def _focus(self, user_id: UUID, refs: tuple[RecordRef, ...], reference: datetime) -> None:
        await self.repository.set_progress(
            user_id,
            MemoryProgress(
                consent_id=await self.repository.lock(user_id),
                reference_time_utc=reference,
                focus=refs[:32],
            ),
        )

    async def _ask(
        self,
        user_id: UUID,
        *,
        action: Literal["read", "delete", "correct", "learn"],
        message: ChannelMessage,
        choices: tuple[SavedRecord, ...],
        question: str,
        cascade: bool = False,
        awaiting_date: bool = False,
        operation_source: UUID | None = None,
        timezone: str | None = None,
        timezone_source: Literal["explicit_event", "current_preference"] = "current_preference",
    ) -> str:
        rendered = question + "".join(f"\n{i}. {describe(s)}" for i, s in enumerate(choices, 1))
        if len(choices) > 20 or len(rendered.encode("utf-16-le")) // 2 > 3900:
            return "Which person or event do you mean? Please give a more specific name or date."
        dependencies = (
            await self.repository.dependents(user_id, choices[0].record.id) if cascade else set()
        )
        cascade_refs = tuple(
            s.ref for s in await self.repository.list(user_id) if s.record.id in dependencies
        )
        await self.repository.set_progress(
            user_id,
            MemoryProgress(
                consent_id=await self.repository.lock(user_id),
                reference_time_utc=message.received_at,
                action=action,
                text=message.text,
                choices=tuple(s.ref for s in choices),
                focus=tuple(s.ref for s in choices),
                confirm_cascade=cascade,
                cascade_refs=cascade_refs,
                awaiting_date=awaiting_date,
                source_message_id=operation_source or source_id(user_id, message),
                timezone=timezone,
                timezone_source=timezone_source,
            ),
        )
        if cascade:
            return question
        return rendered

    async def resume(
        self, user_id: UUID, message: ChannelMessage, *, controls: bool = False
    ) -> MemoryTurn:
        progress = await self.repository.progress(user_id)
        if (
            progress is None
            or progress.action is None
            or ((progress.action in {"read", "delete"}) != controls)
        ):
            return MemoryTurn(message)
        if (
            NO_REMEMBER.search(message.text)
            or private_active_input(message.text)
            or is_harmful_request(message.text)
        ):
            return MemoryTurn(message)
        value = normalize(message.text).strip(" .!")
        if value in {"cancel", "never mind", "nevermind"}:
            await self.repository.clear_progress(user_id)
            return MemoryTurn(message, reply="Cancelled.")
        records = tuple(
            [
                s
                for ref in progress.choices
                if (s := await self.repository.get(user_id, ref)) is not None
            ]
        )
        if len(records) != len(progress.choices):
            await self.repository.clear_progress(user_id)
            return MemoryTurn(
                message, reply="Those saved details changed. Please name the event again."
            )
        selected = None
        force_new = False
        confirmed = False
        if progress.awaiting_date and records and len(message.text) <= 256:
            from oria_engine.domain.temporal import analyze_temporal

            analysis = analyze_temporal(message.text, received_at=progress.reference_time_utc)
            if len(analysis.mentions) == 1 and analysis.mentions[0].start == 0:
                return MemoryTurn(
                    replace(
                        message,
                        text=f"correct {names(records[0].record)[0]} to {message.text}",
                        received_at=progress.reference_time_utc,
                    ),
                    selected=records[0].ref,
                    source=progress.source_message_id,
                    timezone=progress.timezone,
                    timezone_source=progress.timezone_source,
                )
        if progress.action == "learn" and not records:
            candidate = entity_from(message.text)
            if candidate:
                subject = (
                    candidate.label
                    if candidate.label.startswith("my ")
                    else f"my {candidate.relationship} {candidate.label}"
                )
                text = re.sub(
                    r"\b(?:her|his|their|she|he|they)\b", subject, progress.text, flags=re.I
                )
                return MemoryTurn(
                    replace(message, text=text, received_at=progress.reference_time_utc),
                    source=progress.source_message_id,
                    timezone=progress.timezone,
                    timezone_source=progress.timezone_source,
                )
        if progress.confirm_cascade and value in {
            "yes",
            "yes delete",
            "yes forget",
            "delete them",
            "forget them",
        }:
            selected, confirmed = records[0].ref, True
        elif progress.action == "learn" and value in {
            "another",
            "another event",
            "a different event",
            "another person",
        }:
            force_new = True
        elif re.fullmatch(r"(?:the )?(?:first|second|third)(?: one)?|\d{1,2}", value):
            number = {"first": 1, "second": 2, "third": 3}.get(
                re.sub(r"^(?:the )?| one$", "", value)
            )
            if number is None and value.isdigit():
                number = int(value)
            if number and 1 <= number <= len(records):
                selected = records[number - 1].ref
        elif (
            value in {"same", "same event", "correct it", "it is a correction"}
            and len(records) == 1
        ):
            selected = records[0].ref
        else:
            by_name = [s for s in records if matches(value, s)]
            if len(by_name) == 1 and len(value.split()) <= 8:
                selected = by_name[0].ref
        if selected is not None or force_new:
            await self._focus(user_id, (selected,) if selected else (), progress.reference_time_utc)
            return MemoryTurn(
                replace(message, text=progress.text, received_at=progress.reference_time_utc),
                selected=selected,
                force_new=force_new,
                cascade_confirmed=confirmed,
                cascade_refs=progress.cascade_refs,
                source=progress.source_message_id,
                timezone=progress.timezone,
                timezone_source=progress.timezone_source,
            )
        # An explicit new request abandons the pending action. A random "yes" never deletes.
        if value in {"yes", "no"} or value.isdigit():
            return MemoryTurn(message, reply="Please choose a numbered record, or say cancel.")
        await self.repository.clear_progress(user_id)
        return MemoryTurn(message)

    async def controls(
        self, user_id: UUID, message: ChannelMessage, command: str | None = None
    ) -> str | None:
        if (
            message.callback_data
            or private_active_input(message.text)
            or is_harmful_request(message.text)
        ):
            return None
        turn = await self.resume(user_id, message, controls=True)
        if turn.reply:
            return turn.reply
        message = turn.message
        request = directive(message.text)
        if command in {"memory", "memories"}:
            request = Directive("read", message.text.partition(" ")[2])
        if request is None or request.action not in {"read", "delete"}:
            return None
        records = await self.repository.list(user_id)
        own_birth = bool(re.search(r"\bmy (?:birth|birthday|date of birth)\b", request.query))
        if own_birth and request.action == "read":
            profile = await BirthProfileRepository(
                self.session, self.encryption, policy_version=self.policy_version
            ).get(user_id)
            return (
                (
                    f"Your saved birth date is {profile.birth_date.isoformat()}. "
                    "Use /profile for the full birth profile."
                )
                if profile
                else "Your birth profile is not saved."
            )
        selected = (
            tuple(s for s in records if s.ref == turn.selected)
            if turn.selected
            else tuple(s for s in records if self._matches(request.query, s, records))
        )
        if own_birth and request.action == "delete":
            own = await self.repository.own_birth(user_id)
            selected = (own,) if own else ()
        # "Forget that" and brief follow-up questions use current, owner-validated focus.
        if normalize(request.query) in {"it", "that", "this", "that event", "this event"}:
            progress = await self.repository.progress(user_id)
            selected = tuple(
                [
                    s
                    for ref in (progress.focus if progress else ())
                    if (s := await self.repository.get(user_id, ref)) is not None
                ]
            )
        if request.action == "read":
            if not selected:
                if re.search(r"\b(?:my birth|my birthday|I was born)\b", message.text, re.I):
                    profile = await BirthProfileRepository(
                        self.session, self.encryption, policy_version=self.policy_version
                    ).get(user_id)
                    if profile:
                        return (
                            f"Your saved birth date is {profile.birth_date.isoformat()}. "
                            "Use /profile for the full birth profile."
                        )
                return "I don't have a saved event or entity matching that."
            await self._focus(user_id, tuple(s.ref for s in selected), message.received_at)
            return bounded_reply("Here is what is saved in your private profile:", selected)
        if not selected:
            return "There is no matching saved event or entity to remove."
        if not turn.selected and any(isinstance(s.record, EntityRecord) for s in selected):
            selected = tuple(s for s in selected if isinstance(s.record, EntityRecord))
        if len(selected) > 1:
            return await self._ask(
                user_id,
                action="delete",
                message=message,
                choices=selected,
                question="Which saved record should I remove?",
                operation_source=turn.source,
            )
        saved = selected[0]
        dependencies = await self.repository.dependents(user_id, saved.record.id)
        current_dependencies = {s.ref for s in records if s.record.id in dependencies}
        if dependencies and (
            not turn.cascade_confirmed or current_dependencies != set(turn.cascade_refs)
        ):
            return await self._ask(
                user_id,
                action="delete",
                message=message,
                choices=selected,
                question=(
                    f"Removing {names(saved.record)[0]} also removes {len(dependencies)} "
                    "linked event record(s). Remove them too? Say yes or cancel."
                ),
                cascade=True,
                operation_source=turn.source,
            )
        if not await self.repository.claim(
            user_id, turn.source or source_id(user_id, message), learning=False
        ):
            return "This request was already processed; no additional records were removed."
        count = await self.repository.erase(user_id, saved.ref)
        from oria_engine.db.projections import ProjectionRepository

        pending = any(
            row.deleted and row.pending
            for row in await ProjectionRepository(
                self.session, self.encryption, self.policy_version
            ).rows(user_id)
        )
        return (
            f"Removed {count} saved record(s) from your private profile. "
            + (
                "SecondContext removal is queued and will retry until acknowledged. "
                if pending
                else ""
            )
            + "Prior chat/provider copies have separate retention; "
            "/delete_me removes the account history."
        )

    async def anchors(
        self, user_id: UUID, selected: RecordRef | None = None
    ) -> tuple[EventAnchor, ...]:
        result = []
        records = await self.repository.list(user_id)
        for saved in records:
            if selected is not None and selected.kind == "event" and saved.ref != selected:
                continue
            record = saved.record
            if not isinstance(record, EventRecord) or saved.needs_review or record.temporal is None:
                continue
            value = record.temporal.value
            if getattr(value, "approximate", False):
                continue  # A remembered approximate date is not an exact calculation anchor.
            day = (
                value.value
                if isinstance(value, CalendarDate)
                else value.value.date()
                if isinstance(value, (Instant, LocalDateTime))
                else None
            )
            if isinstance(value, Instant) and record.temporal.timezone:
                day = value.value.astimezone(birth_zone(record.temporal.timezone)).date()
            if not isinstance(day, date):
                continue
            labels = [record.description]
            if record.event_type == "wedding":
                labels += ["our wedding day", "my wedding", "my wedding day"]
            elif record.event_type == "purchase" and "house" in record.description:
                labels += ["the day I bought my house"]
            elif record.event_type == "adoption" and "cat" in record.description:
                labels += ["the day I got the cat"]
            elif record.event_type == "job change":
                labels += ["the day I changed my job"]
            elif record.event_type == "founding":
                labels += ["the day I founded my business"]
            elif record.event_type == "divorce":
                labels += ["the day my parents got divorced"]
            if record.event_type == "birth":
                entities = [
                    s.record
                    for s in records
                    if isinstance(s.record, EntityRecord)
                    and s.record.id in {p.entity_id for p in record.participants}
                ]
                for entity in entities:
                    labels += [f"{label}'s birthday" for label in (entity.label, *entity.aliases)]
            for label in dict.fromkeys(labels):
                if len(label) <= 160:
                    result.append(
                        EventAnchor(
                            label=label,
                            day=day,
                            recurring="birthday" in label or "anniversary" in label,
                            reference=saved.ref,
                        )
                    )
        return tuple(result[:1000])

    async def clarify_anchor(
        self, user_id: UUID, message: ChannelMessage, label: str | None
    ) -> str | None:
        if label is None:
            return None
        anchors = await self.anchors(user_id)
        refs = {a.reference for a in anchors if a.label.casefold() == label.casefold()}
        if len(refs) <= 1:
            return None
        records = tuple(s for s in await self.repository.list(user_id) if s.ref in refs)
        return await self._ask(
            user_id,
            action="learn",
            message=message,
            choices=records,
            question="Which saved occurrence do you mean?",
        )

    async def _entity(
        self,
        user_id: UUID,
        candidate: EntityCandidate,
        source: UUID,
        records: tuple[SavedRecord, ...],
        selected: RecordRef | None = None,
        force_new: bool = False,
    ) -> SavedRecord | tuple[SavedRecord, ...]:
        possible = tuple(
            s
            for s in records
            if isinstance(s.record, EntityRecord)
            and (
                {normalize(n) for n in names(s.record)}
                & {normalize(n) for n in (candidate.label, *candidate.aliases)}
            )
        )
        exact = tuple(
            s
            for s in possible
            if isinstance(s.record, EntityRecord)
            and normalize(s.record.label) == normalize(candidate.label)
        )
        if exact:
            possible = exact
        if selected and selected.kind == "entity":
            possible = tuple(s for s in records if s.ref == selected)
        if force_new:
            possible = ()
        if len(possible) > 1:
            return possible
        if possible:
            saved = possible[0]
            record = saved.record
            assert isinstance(record, EntityRecord)
            if candidate.label != record.label and candidate.label not in record.aliases:
                # A new name for an occupied relationship is not evidence of identity.
                if (
                    selected is None
                    and record.label
                    not in (
                        candidate.label,
                        *candidate.aliases,
                    )
                    and not record.label.startswith(("my ", "our "))
                ):
                    return possible
                aliases = tuple(dict.fromkeys((*record.aliases, record.label, *candidate.aliases)))
                updated: EntityRecord | EventRecord = EntityRecord.model_validate(
                    {
                        **record.model_dump(),
                        "label": candidate.label,
                        "aliases": aliases[:20],
                        "revision": record.revision + 1,
                        "source_message_id": source,
                    }
                )
                return await self.repository.save(user_id, updated)
            return saved
        return await self.repository.save(
            user_id,
            EntityRecord(
                id=uuid4(),
                revision=1,
                entity_type=candidate.entity_type,
                label=candidate.label,
                aliases=candidate.aliases,
                relationship_to_user=candidate.relationship,
                source_message_id=source,
            ),
        )

    async def learn(
        self, user_id: UUID, turn: MemoryTurn, dialogue: TemporalDialogue
    ) -> str | None:
        message = replace(turn.message, text=dialogue.text, received_at=dialogue.reference)
        if NO_REMEMBER.search(dialogue.text):
            await self.repository.clear_progress(user_id)
            return "I won't add this to your saved events or entities."
        request = directive(dialogue.text)
        records = await self.repository.list(user_id)
        progress = await self.repository.progress(user_id)
        source = (
            dialogue.operation_source
            or turn.source
            or source_id(
                user_id,
                replace(
                    message,
                    provider_update_id=dialogue.source_update_id or message.provider_update_id,
                ),
            )
        )
        if request and request.action == "correct":
            chosen = (
                tuple(s for s in records if s.ref == turn.selected)
                if turn.selected
                else tuple(
                    s
                    for s in records
                    if self._matches(
                        re.split(
                            r"\b(?:to|was|is|name|relationship|place|location)\b", request.query
                        )[0],
                        s,
                        records,
                    )
                )
            )
            if request.query.startswith(("it ", "that ")) or normalize(message.text).startswith(
                ("it was", "that was", "actually")
            ):
                chosen = tuple(
                    [
                        s
                        for ref in (progress.focus if progress else ())
                        if (s := await self.repository.get(user_id, ref)) is not None
                    ]
                )
                chosen = tuple(s for s in chosen if isinstance(s.record, EventRecord)) or chosen
            if re.search(r"\b(?:name|relationship)\b", request.query):
                chosen = tuple(s for s in chosen if isinstance(s.record, EntityRecord))
            if re.search(r"\bmy (?:birth|birthday|date of birth)\b", request.query):
                return "Use /edit_profile to correct your own saved birth details."
            if len(chosen) != 1:
                return await self._ask(
                    user_id,
                    action="correct",
                    message=message,
                    operation_source=source,
                    timezone=dialogue.timezone,
                    timezone_source=dialogue.timezone_source,
                    choices=chosen
                    or tuple(s for s in records if isinstance(s.record, EventRecord)),
                    question="Which saved record should I correct?",
                )
            saved = chosen[0]
            record = saved.record
            if isinstance(record, EntityRecord):
                rename = re.search(
                    r"\b(?:name (?:is|to)|called|rename .+ to)\s+(.+)", dialogue.text, re.I
                )
                relation = re.search(r"\brelationship (?:is|to)\s+(.+)", dialogue.text, re.I)
                if rename is None and relation is None:
                    return (
                        "What should change? You can say “correct its name to …” or “correct "
                        "its relationship to …”."
                    )
                changes = record.model_dump()
                if rename:
                    changes.update(
                        label=rename[1].strip(" .")[:160],
                        aliases=tuple(dict.fromkeys((*record.aliases, record.label)))[:20],
                    )
                if relation:
                    relationship = relation[1].strip(" .")[:157]
                    old_relation = record.relationship_to_user
                    aliases = tuple(
                        alias for alias in record.aliases if alias != f"my {old_relation}"
                    )
                    changes.update(
                        relationship_to_user=relationship,
                        aliases=tuple(dict.fromkeys((*aliases, f"my {relationship}")))[:20],
                    )
                    if record.label == f"my {old_relation}":
                        changes["label"] = f"my {relationship}"
                changes.update(revision=record.revision + 1, source_message_id=source)
                updated: EntityRecord | EventRecord = EntityRecord.model_validate(changes)
            elif place_change := re.search(r"\b(?:place|location) to\s+(.+)", dialogue.text, re.I):
                updated = EventRecord.model_validate(
                    {
                        **record.model_dump(),
                        "place": place_change[1].strip(" ."),
                        "revision": record.revision + 1,
                        "source_message_id": source,
                    }
                )
            else:
                # The first date is the replacement; a "not ..." suffix quotes the old value.
                dates = [
                    m
                    for m in dialogue.analysis.mentions
                    if not re.search(r"\bnot\b", dialogue.text[: m.start], re.I)
                    and m.evidence.anchor != saved.ref
                ]
                if not dates or dates[0].issue:
                    return await self._ask(
                        user_id,
                        action="correct",
                        message=message,
                        operation_source=source,
                        timezone=dialogue.timezone,
                        timezone_source=dialogue.timezone_source,
                        choices=(saved,),
                        awaiting_date=True,
                        question="What is the correct date for that event?",
                    )
                evidence = dates[0].evidence
                if evidence.value is None:
                    return "What is the correct date for that event?"
                value = evidence.value
                old = record.temporal.value if record.temporal else None
                if (
                    isinstance(value, PartialDate)
                    and value.year is None
                    and value.month
                    and value.day
                    and isinstance(old, CalendarDate)
                ):
                    try:
                        evidence = TemporalEvidence.model_validate(
                            {
                                **evidence.model_dump(),
                                "value": CalendarDate(
                                    value=date(old.value.year, value.month, value.day),
                                    approximate=value.approximate,
                                ),
                            }
                        )
                    except ValueError:
                        return "Which year should I use for that corrected date?"
                updated = EventRecord.model_validate(
                    {
                        **record.model_dump(),
                        "temporal": evidence,
                        "revision": record.revision + 1,
                        "source_message_id": source,
                    }
                )
            if not await self.repository.claim(user_id, source):
                return "This correction was already processed."
            changed = await self.repository.save(user_id, updated)
            await self._focus(user_id, (changed.ref,), message.received_at)
            return "Updated in your private profile: " + describe(changed)
        # No generic model-directed extraction. A pronoun needs one current entity focus.
        entity_focus = [
            s.record
            for ref in (progress.focus if progress else ())
            if (s := await self.repository.get(user_id, ref)) is not None
            and isinstance(s.record, EntityRecord)
        ]
        if not entity_focus and progress:
            event_focus = [
                s.record
                for ref in progress.focus
                if (s := await self.repository.get(user_id, ref)) is not None
                and isinstance(s.record, EventRecord)
            ]
            entity_ids = {p.entity_id for event in event_focus for p in event.participants}
            entity_focus = [
                s.record
                for s in records
                if isinstance(s.record, EntityRecord) and s.record.id in entity_ids
            ]
        pronoun = (
            EntityCandidate(
                entity_focus[0].label,
                entity_focus[0].entity_type,
                entity_focus[0].relationship_to_user,
                entity_focus[0].aliases,
            )
            if len(entity_focus) == 1
            else None
        )
        known_entities = tuple(
            EntityCandidate(
                s.record.label,
                s.record.entity_type,
                s.record.relationship_to_user,
                s.record.aliases,
            )
            for s in records
            if isinstance(s.record, EntityRecord)
        )
        candidates = extract_events(dialogue.text, pronoun=pronoun, known_entities=known_entities)
        entity_statement = re.fullmatch(
            r"(?:My|my|Our|our) (.+?) (?:is|is named|is called) ([A-Z][\w' -]{0,100})[.!]?",
            dialogue.text.strip(),
        )
        if not candidates and entity_statement:
            entity_candidate = entity_from(
                f"my {entity_statement[1]} {entity_statement[2].rstrip('.! ')}"
            )
            if entity_candidate is not None:
                try:
                    async with self.session.begin_nested():
                        if not await self.repository.claim(user_id, source):
                            return "This information was already processed."
                        entity_result = await self._entity(
                            user_id,
                            entity_candidate,
                            source,
                            records,
                            turn.selected,
                            turn.force_new,
                        )
                        if isinstance(entity_result, tuple):
                            raise MemoryQuestion(
                                entity_result,
                                "Which entity is this? Choose one, or say “another person”.",
                            )
                except MemoryQuestion as question:
                    return await self._ask(
                        user_id,
                        action="learn",
                        message=message,
                        operation_source=source,
                        timezone=dialogue.timezone,
                        timezone_source=dialogue.timezone_source,
                        choices=question.choices,
                        question=question.question,
                    )
                await self._focus(user_id, (entity_result.ref,), message.received_at)
                return "Saved in your private profile: " + describe(entity_result)
        if not candidates:
            if (
                re.search(
                    r"\b(?:her|his|their) birthday (?:is|was)|\b(?:she|he|they) was born",
                    dialogue.text,
                    re.I,
                )
                and pronoun is None
                and requested_follow_up(dialogue.text) is None
            ):
                choices = tuple(s for s in records if isinstance(s.record, EntityRecord))
                return await self._ask(
                    user_id,
                    action="learn",
                    message=message,
                    operation_source=source,
                    timezone=dialogue.timezone,
                    timezone_source=dialogue.timezone_source,
                    choices=choices,
                    question=(
                        "Who do you mean? Choose a saved entity or give a name "
                        "such as “my girlfriend Alice”."
                    ),
                )
            return None
        # Save an entire multi-event turn atomically, including any ambiguity rollback.
        acknowledgements = []
        focus = []
        try:
            async with self.session.begin_nested():
                if not await self.repository.claim(user_id, source):
                    return (
                        "This information was already processed; no additional records were saved."
                    )
                for candidate in candidates:
                    participants = []
                    for entity in candidate.participants:
                        saved_entity = await self._entity(
                            user_id, entity, source, records, turn.selected, turn.force_new
                        )
                        if isinstance(saved_entity, tuple):
                            raise MemoryQuestion(
                                saved_entity,
                                "Which entity is this? Choose one, or say “another person”.",
                            )
                        participants.append(
                            Participant(
                                entity_id=saved_entity.record.id,
                                role=entity.relationship or "participant",
                            )
                        )
                        focus.append(saved_entity.ref)
                        records = await self.repository.list(user_id)
                    mentions = [
                        m
                        for m in dialogue.analysis.mentions
                        if candidate.start <= m.start < candidate.end
                    ]
                    if len(mentions) > 1:
                        raise MemoryQuestion(
                            (),
                            "Which date belongs to that event? "
                            "Please describe each occurrence separately.",
                        )
                    temporal = mentions[0].evidence if mentions else None
                    label = candidate.label
                    if candidate.event_type == "life event":
                        for mention in mentions:
                            label = label.replace(mention.evidence.expression, "").strip(" ,")
                        label = re.sub(r"\s+(?:in|on|at)$", "", label, flags=re.I)
                    participant_ids = {p.entity_id for p in participants}
                    existing = tuple(
                        s
                        for s in records
                        if isinstance(s.record, EventRecord)
                        and s.record.event_type == candidate.event_type
                        and (participant_ids or s.record.description == label)
                        and {p.entity_id for p in s.record.participants} == participant_ids
                    )
                    if turn.selected and turn.selected.kind == "event":
                        existing = tuple(s for s in existing if s.ref == turn.selected)
                    if turn.force_new:
                        existing = ()
                    if existing and not turn.selected:
                        same = [
                            s
                            for s in existing
                            if isinstance(s.record, EventRecord)
                            and (s.record.temporal.value if s.record.temporal else None)
                            == (temporal.value if temporal else None)
                        ]
                        if len(same) == 1:
                            focus.append(same[0].ref)
                            acknowledgements.append(describe(same[0]))
                            continue
                        raise MemoryQuestion(
                            existing,
                            "Is this a correction to a saved occurrence, or another event? Choose "
                            "a record, or say “another event”.",
                        )
                    previous = existing[0].record if len(existing) == 1 else None
                    record = EventRecord(
                        id=previous.id if previous else uuid4(),
                        revision=previous.revision + 1 if previous else 1,
                        event_type=candidate.event_type,
                        description=label,
                        participants=tuple(participants),
                        temporal=temporal,
                        place=supplied_place(dialogue.text[candidate.start : candidate.end]),
                        source_message_id=source,
                    )
                    saved = await self.repository.save(user_id, record)
                    focus.append(saved.ref)
                    acknowledgements.append(describe(saved))
                    records = await self.repository.list(user_id)
        except KnowledgeConflict:
            return (
                "Those details could not be saved. Please inspect /memories and choose "
                "an existing record to correct, or remove unneeded records."
            )
        except MemoryQuestion as question:
            if not question.choices:
                return question.question
            return await self._ask(
                user_id,
                action="learn",
                message=message,
                operation_source=source,
                timezone=dialogue.timezone,
                timezone_source=dialogue.timezone_source,
                choices=question.choices,
                question=question.question,
            )
        await self._focus(user_id, tuple(focus), message.received_at)
        return cap_reply("Saved in your private profile:\n" + "\n".join(acknowledgements))
