"""Synthetic wire smoke check; run inside the released worker with its private settings.

No Telegram messages or canonical user records are created. --generate additionally
calls the configured AI provider. Only newly allocated subjects are purged; request
payloads, credentials and generated text are never printed.
"""

import argparse
import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

from oria_engine.astrology.client import FastMCPAstrologyClient
from oria_engine.astrology.linked import ChartInput, ChartRequest, SynastryRequest
from oria_engine.config import Settings
from oria_engine.context.contracts import ContextScope, ContextUnavailable, ConversationRequest
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.domain.policy import guard_reply
from oria_engine.domain.readings import (
    LinkedReading,
    ReadingChart,
    ReadingComparison,
    requested_rating,
)
from oria_engine.knowledge.contracts import (
    ContextProjection,
    ProjectionDelete,
    ProjectionQuery,
    ProjectionUpsert,
    RecordRef,
)


async def check(generate: bool) -> None:
    settings = Settings()
    provider = SecondContextProvider(settings)
    owners = (uuid4(), uuid4())
    stage = "capabilities"
    cleanup_failed = False
    try:
        for owner in owners:
            await provider.projection_capabilities(owner)
        subject = provider.subject(owners[0])
        original = RecordRef(kind="entity", id=uuid4(), revision=1)
        projection = ContextProjection(
            record=original,
            label="Synthetic release partner",
            summary="A voluntarily described partner.",
            knowledge_kind="user_statement",
            sources=(original,),
            house_themes=(4, 7, 8),
        )
        write = ProjectionUpsert(user=subject, operation_id=uuid4(), projection=projection)
        stage = "idempotent projection and owner isolation"
        await provider.project(write)
        await provider.project(write)
        query = ProjectionQuery(user=subject, references=(original,))
        matches = await provider.query_projections(query)
        assert matches.matches == (projection,)
        other = await provider.query_projections(
            query.model_copy(update={"user": provider.subject(owners[1])})
        )
        assert not other.matches

        stage = "published linked astrology tools"
        astro = FastMCPAstrologyClient(settings.astrology_mcp_url)
        own = ChartInput(
            accuracy="exact",
            timestamp_utc=datetime(1990, 4, 13, 0, 42, tzinfo=UTC),
            latitude=46.77,
            longitude=23.59,
        )
        partner = ChartInput(accuracy="unknown", calendar_date=date(1992, 6, 2))
        event = await astro.calculate_event_chart(
            ChartRequest(
                calculation_id=uuid4(),
                chart=ChartInput(accuracy="unknown", calendar_date=date(2020, 5, 1)),
            )
        )
        synastry = await astro.calculate_synastry(
            SynastryRequest(calculation_id=uuid4(), chart_a=own, chart_b=partner)
        )
        assert event.chart.precision == "date_sample" and not event.chart.house_cusps
        assert synastry.chart_a.house_cusps and not synastry.chart_b.house_cusps
        assert synastry.aspects and synastry.overlays
        comparisons = [
            ReadingComparison(
                a="self", b="other", aspects=synastry.aspects, overlays=synastry.overlays
            )
        ]
        facts = LinkedReading(
            kind="compatibility",
            charts=(
                ReadingChart(role="self", facts=synastry.chart_a),
                ReadingChart(role="other", facts=synastry.chart_b),
                ReadingChart(role="event", convention="event", facts=event.chart),
            ),
            comparisons=tuple(comparisons),
            sources=(original,),
            house_themes=tuple(range(1, 13)),
            rating=requested_rating("Rate our compatibility", comparisons),
        )
        if generate:
            stage = "live provider generation with linked facts"
            reply = await provider.respond(
                ContextScope(user_id=owners[0], session_id=uuid4()),
                ConversationRequest(
                    filtered_message="Rate this compatibility. Discuss home and partnership.",
                    linked_facts=facts,
                    knowledge_refs=(original,),
                ),
            )
            assert reply.text.strip()
            assert guard_reply(reply.text) == reply.text

        stage = "correction and stale dependency rejection"
        corrected = original.model_copy(update={"revision": 2})
        await provider.project(
            ProjectionUpsert(
                user=subject,
                operation_id=uuid4(),
                projection=projection.model_copy(
                    update={"record": corrected, "sources": (corrected,)}
                ),
            )
        )
        try:
            await provider.respond(
                ContextScope(user_id=owners[0], session_id=uuid4()),
                ConversationRequest(
                    filtered_message="Synthetic stale check", knowledge_refs=(original,)
                ),
            )
        except ContextUnavailable:
            pass
        else:
            raise AssertionError("Stale source accepted")
        stage = "selective erasure and replay fence"
        if generate:
            await provider.respond(
                ContextScope(user_id=owners[0], session_id=uuid4()),
                ConversationRequest(
                    filtered_message="Reflect briefly on the supplied compatibility facts.",
                    linked_facts=facts.model_copy(update={"sources": (corrected,)}),
                    knowledge_refs=(corrected,),
                ),
            )
        deletion = ProjectionDelete(
            user=subject,
            operation_id=uuid4(),
            record=corrected.model_copy(update={"revision": 3}),
        )
        await provider.project(deletion)
        await provider.project(deletion)
        assert not (await provider.query_projections(query)).matches
        try:
            await provider.project(
                ProjectionUpsert(
                    user=subject,
                    operation_id=uuid4(),
                    projection=projection.model_copy(
                        update={
                            "record": original.model_copy(update={"revision": 4}),
                            "sources": (original.model_copy(update={"revision": 4}),),
                        }
                    ),
                )
            )
        except ContextUnavailable:
            pass
        else:
            raise AssertionError("Deleted source resurrected")
        stage = "subject purge and delayed write fence"
        await provider.purge(owners[0])
        await provider.purge(owners[0])
        try:
            await provider.project(write)
        except ContextUnavailable:
            pass
        else:
            raise AssertionError("Purged subject accepted a delayed write")
    except Exception:
        raise RuntimeError(
            f"Release check failed during {stage}; private payloads withheld"
        ) from None
    finally:
        for owner in owners:
            try:
                await provider.purge(owner)
            except Exception:
                cleanup_failed = True
        await provider.aclose()
        if cleanup_failed:
            raise RuntimeError(
                "Synthetic subject cleanup is incomplete; retry purge privately"
            ) from None
    print("PASS: linked tools, scope, revisions, selective erasure and full purge")
    if generate:
        print("PASS: configured provider generated a linked reading")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generate", action="store_true", help="also call the configured AI provider"
    )
    asyncio.run(check(parser.parse_args().generate))
