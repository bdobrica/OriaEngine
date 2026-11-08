"""Linked salience/interpretations over the scoped HTTP contract, never direct SQL.

No dates, places, birth inputs or arbitrary canonical descriptions are projected.
All remote text remains untrusted; local desired state and current canonical source
revisions must both match before a recollection can enter generation.
"""

import re
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from oria_engine.context.contracts import ContextUnavailable
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.db.birth_profiles import BirthProfileRepository
from oria_engine.db.models import Consent, ContextProjectionWork
from oria_engine.db.projections import ProjectionRepository
from oria_engine.db.repositories import ConsentRepository, UserRepository
from oria_engine.db.session import Database
from oria_engine.domain.knowledge import KnowledgeConversation, names
from oria_engine.domain.projections import canonical_projection, safe_text, themes
from oria_engine.knowledge.contracts import (
    ContextProjection,
    EventRecord,
    ProjectionDelete,
    ProjectionQuery,
    ProjectionUpsert,
    RecordRef,
    Salience,
)
from oria_engine.privacy.encryption import ProfileEncryption


class LinkedContext:
    def __init__(
        self,
        session: AsyncSession,
        encryption: ProfileEncryption,
        policy_version: str,
        provider: SecondContextProvider,
    ):
        self.session, self.provider = session, provider
        self.repo = ProjectionRepository(session, encryption, policy_version)
        self.knowledge = self.repo.knowledge
        self.conversation = KnowledgeConversation(session, encryption, policy_version)

    async def stage(self, user_id: UUID) -> None:
        await self.knowledge.lock(user_id, write=True)
        records = await self.knowledge.list(user_id)
        own = await self.knowledge.own_birth(user_id)
        for saved in (*records, *((own,) if own else ())):
            if not saved.needs_review:
                await self.repo.put(user_id, canonical_projection(saved))
        by_id = {s.ref.id: s for s in records}
        # Separate link observations get a new UUID when a dependency changes;
        # canonical event identity/revision is never invented by the projection.
        for saved in records:
            r = saved.record
            if not isinstance(r, EventRecord) or saved.needs_review or not r.participants:
                continue
            participants = tuple(by_id[p.entity_id] for p in r.participants if p.entity_id in by_id)
            sources = (saved.ref, *(p.ref for p in participants))
            identity = ":".join(f"{ref.id}:{ref.revision}" for ref in sources)
            labels = [canonical_projection(p).label for p in participants]
            summary = (
                f"The user's {canonical_projection(saved).label} involves {', '.join(labels)}."
            )
            await self.repo.put(
                user_id,
                ContextProjection(
                    record=RecordRef(
                        kind="reading",
                        id=uuid5(NAMESPACE_URL, f"oria:links:{user_id}:{identity}"),
                        revision=1,
                    ),
                    label="Event participants",
                    summary=summary[:2048],
                    knowledge_kind="user_statement",
                    sources=sources[:32],
                    house_themes=themes(summary),
                    salience=Salience(
                        score=0.5, basis="inferred", method_version="linked-salience-1"
                    ),
                ),
            )
        for row in await self.repo.rows(user_id):
            if (
                row.kind == "reading"
                and not row.deleted
                and not await self.repo.current(user_id, self.repo.decode(row))
            ):
                await self.repo.retire(row)

    async def references(self, user_id: UUID, text: str) -> tuple[RecordRef, ...]:
        own_pattern = r"\b(?:my (?:birthday|birth|date of birth)|(?:the )?day I was born)\b"
        own = (
            await self.knowledge.own_birth(user_id) if re.search(own_pattern, text, re.I) else None
        )
        lookup = re.sub(own_pattern, "", text, flags=re.I) if own else text
        records = await self.knowledge.list(user_id)
        selected = tuple(
            s.ref
            for s in records
            if lookup.strip()
            and not s.needs_review
            and self.conversation._matches(lookup, s, records)
        )
        if not selected:
            # CRUD selectors require a whole-query match. Recall instead detects
            # known names/aliases within ordinary sentences, then follows scoped links.
            mentioned = {
                saved.ref.id
                for saved in records
                if not saved.needs_review
                and any(
                    len(label) >= 3
                    and re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", lookup, re.I)
                    for label in names(saved.record)
                )
            }
            mentioned.update(
                saved.ref.id
                for saved in records
                if isinstance(saved.record, EventRecord)
                and any(p.entity_id in mentioned for p in saved.record.participants)
            )
            selected = tuple(s.ref for s in records if s.ref.id in mentioned and not s.needs_review)
        # Only actual pronoun/follow-up language activates previous focus.
        if (
            not selected
            and own is None
            and re.search(
                r"\b(?:she|her|he|him|they|them|that|this|it|same|our relationship)\b", text, re.I
            )
        ):
            progress = await self.knowledge.progress(user_id)
            if progress:
                selected = tuple(
                    [
                        ref
                        for ref in progress.focus
                        if (saved := await self.knowledge.get(user_id, ref))
                        and not saved.needs_review
                    ]
                )
        if own is not None:
            selected = (own.ref, *selected)
        return selected[:32]

    async def observe(self, user_id: UUID, text: str, operation_id: UUID) -> None:
        refs = await self.references(user_id, text)
        low = re.search(
            r"\b(?:not (?:very |especially )?important|doesn't matter|does not matter|"
            r"no longer important|unimportant)\b",
            text,
            re.I,
        )
        high = re.search(
            r"\b(?:very important|most important|means a lot|especially important)\b", text, re.I
        )
        if refs and (low or high) and not re.search(r"\b(?:if|imagine|example)\b|\?", text, re.I):
            # Keep the explicit statement's meaning without its raw wording/dates.
            significance = "less important now" if low else "especially important"
            for row in await self.repo.rows(user_id):
                if not row.deleted:
                    old = self.repo.decode(row)
                    if old.label == "User-stated significance" and set(old.sources) & set(refs):
                        await self.repo.retire(row)

            await self.repo.put(
                user_id,
                ContextProjection(
                    record=RecordRef(
                        kind="reading",
                        id=uuid5(NAMESPACE_URL, f"oria:importance:{user_id}:{operation_id}"),
                        revision=1,
                    ),
                    label="User-stated significance",
                    summary=f"The user says these linked records are {significance} to them.",
                    knowledge_kind="user_statement",
                    sources=refs,
                    house_themes=themes(text),
                    salience=Salience(
                        score=0.1 if low else 1.0,
                        basis="user_stated",
                        method_version="linked-salience-1",
                    ),
                ),
            )

    async def flush(self, user_id: UUID, *, limit: int = 4) -> bool:
        await self.knowledge.lock(user_id)
        rows = [r for r in await self.repo.rows(user_id) if r.pending]
        if not rows:
            return True
        try:
            await self.provider.projection_capabilities(user_id)
        except ContextUnavailable:
            now = datetime.now(UTC)
            for row in rows[:limit]:
                row.attempts += 1
                row.next_attempt_at = now + timedelta(
                    seconds=min(3600, 10 * 2 ** min(row.attempts - 1, 9))
                )
            return False
        consent = await ConsentRepository(self.session).current(user_id, self.repo.policy_version)
        # Deletes first. While any deletion is pending no recollection is usable.
        rows.sort(key=lambda r: (not r.deleted, r.created_at, r.id))
        now = datetime.now(UTC)
        for row in rows[:limit]:
            if (
                row.next_attempt_at > now
                or not row.deleted
                and (consent is None or not self.provider.knowledge_enabled)
            ):
                continue
            if (
                row.kind == "reading"
                and not row.deleted
                and not await self.repo.current(user_id, self.repo.decode(row))
            ):
                await self.repo.retire(row)
            request = (
                ProjectionDelete(
                    user=self.provider.subject(user_id),
                    operation_id=row.operation_id,
                    record=self.repo.ref(row),
                )
                if row.deleted
                else ProjectionUpsert(
                    user=self.provider.subject(user_id),
                    operation_id=row.operation_id,
                    projection=self.repo.decode(row),
                )
            )
            try:
                await self.provider.project(request)
                row.pending = False
                row.attempts = 0
            except ContextUnavailable:
                row.attempts += 1
                row.next_attempt_at = now + timedelta(
                    seconds=min(3600, 10 * 2 ** min(row.attempts - 1, 9))
                )
                return False
        await self.session.flush()
        return not any(row.pending for row in rows)

    async def retrieve(self, user_id: UUID, text: str) -> tuple[RecordRef, ...]:
        rows = await self.repo.rows(user_id)
        if any(r.pending and r.deleted for r in rows):
            return ()
        refs, houses = await self.references(user_id, text), themes(text)
        if not refs and not houses:
            return ()
        try:
            result = await self.provider.query_projections(
                ProjectionQuery(
                    user=self.provider.subject(user_id),
                    references=refs,
                    house_themes=houses,
                    limit=6,
                )
            )
        except ContextUnavailable:
            return ()
        by_id = {r.id: r for r in rows}
        valid = []
        for projection in result.matches:
            row = by_id.get(projection.record.id)
            if row is None or row.deleted or row.pending:
                continue
            if self.repo.ref(row) != projection.record or self.repo.decode(row) != projection:
                continue
            if not await self.repo.current(user_id, projection):
                continue
            # Reject unsolicited matches, even from an otherwise valid service.
            if not (
                set(refs) & set((projection.record, *projection.sources))
                or set(houses) & set(projection.house_themes)
            ):
                continue
            valid.append(projection.record)
        return tuple(valid)

    async def inspect(self, user_id: UUID, text: str) -> str:
        refs = await self.retrieve(user_id, text)
        summaries = [
            self.repo.decode(row)
            for row in await self.repo.rows(user_id)
            if not row.deleted and self.repo.ref(row) in refs
        ]
        lines = []
        for p in summaries:
            if p.knowledge_kind == "interpretation":
                lines.append("Prior interpretation: " + p.summary)
            elif p.label == "User-stated significance":
                lines.append(p.summary)
        return "\n\n".join(lines)[:2400]

    async def remember_interpretation(
        self, user_id: UUID, text: str, used: tuple[RecordRef, ...], operation_id: UUID
    ) -> None:
        if not used or not safe_text(text):
            return
        profile = await BirthProfileRepository(
            self.session, self.repo.encryption, policy_version=self.repo.policy_version
        ).get(user_id)
        birth_places: list[str] = []
        if profile is not None:
            birth_places.extend(
                filter(
                    None,
                    (
                        profile.birth_place.city,
                        profile.birth_place.region,
                        profile.birth_place.display_name,
                        profile.birth_place.timezone,
                    ),
                )
            )
        birth_places.extend(
            saved.record.place
            for saved in await self.knowledge.list(user_id)
            if isinstance(saved.record, EventRecord)
            and saved.record.event_type == "birth"
            and saved.record.place
        )
        if any(
            re.search(r"(?<!\w)" + re.escape(place) + r"(?!\w)", text, re.I)
            for place in birth_places
        ):
            return
        sources: dict[UUID, RecordRef] = {}
        for row in await self.repo.rows(user_id):
            if not row.deleted and self.repo.ref(row) in used:
                for ref in self.repo.decode(row).sources:
                    sources[ref.id] = ref
        # Active readings receive natal facts even if retrieval selected only an
        # entity/event. A profile correction must invalidate that interpretation.
        own_birth = await self.knowledge.own_birth(user_id)
        if own_birth is not None:
            sources[own_birth.ref.id] = own_birth.ref
        if not sources or len(sources) > 32:
            return
        await self.repo.put(
            user_id,
            ContextProjection(
                record=RecordRef(
                    kind="reading",
                    id=uuid5(NAMESPACE_URL, f"oria:interpretation:{user_id}:{operation_id}"),
                    revision=1,
                ),
                label="Prior interpretation",
                summary=text,
                knowledge_kind="interpretation",
                sources=tuple(sources.values()),
                house_themes=themes(text),
                salience=Salience(score=0.5, basis="inferred", method_version="linked-salience-1"),
            ),
        )


async def recover_projections(
    database: Database,
    encryption: ProfileEncryption,
    policy_version: str,
    provider: SecondContextProvider,
) -> None:
    # Pending selective erasure is retried even after the feature is disabled or
    # consent withdrawn; normal upserts/retrieval require the explicit switch.
    latest_status = (
        select(Consent.status)
        .where(Consent.user_id == ContextProjectionWork.user_id)
        .order_by(Consent.revision.desc())
        .limit(1)
        .scalar_subquery()
    )
    latest_version = (
        select(Consent.policy_version)
        .where(Consent.user_id == ContextProjectionWork.user_id)
        .order_by(Consent.revision.desc())
        .limit(1)
        .scalar_subquery()
    )
    eligible: ColumnElement[bool] = ContextProjectionWork.deleted.is_(True)
    if provider.knowledge_enabled:
        eligible = eligible | ((latest_status == "accepted") & (latest_version == policy_version))
    async with database.transaction() as session:
        owners = list(
            await session.scalars(
                select(ContextProjectionWork.user_id)
                .where(
                    ContextProjectionWork.pending.is_(True),
                    eligible,
                    ContextProjectionWork.next_attempt_at <= datetime.now(UTC),
                )
                .distinct()
                .limit(4)
            )
        )
    for user_id in owners:
        async with database.transaction() as session:
            if await UserRepository(session).get(user_id, for_update=True) is None:
                continue  # Full-subject deletion owns the remaining lifecycle.
            linked = LinkedContext(session, encryption, policy_version, provider)
            await linked.flush(user_id)
