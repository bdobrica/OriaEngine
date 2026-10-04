"""Wire replay acceptance: real persistence, Redis jobs, MCP and HTTP adapters."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from oria_engine.context.contracts import ContextUnavailable
from oria_engine.db.birth_profiles import BirthProfileRepository
from oria_engine.db.models import (
    AstrologyProfile,
    BirthProfile,
    Consent,
    ConversationSession,
    DeletionJob,
    InboundEvent,
    OnboardingProgress,
    SocialIdentity,
    User,
)
from oria_engine.domain.policy import PRIVACY_REPLY, SAFETY_REPLY
from oria_engine.privacy.deletion import FINAL_TEXT, DeletionWorker
from tests.support.replay import scenario_steps


async def count(replay, model):
    async with replay.worker.database.transaction() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def chart(replay, user=42):
    owner = await replay.user_id(user)
    async with replay.worker.database.transaction() as session:
        row = await session.get(AstrologyProfile, owner)
        return row.result if row else None


@pytest.mark.parametrize(
    "scenario,accuracy", [("exact-time", "exact"), ("unknown-time", "unknown")]
)
async def test_onboarding_and_active_facts(replay, scenario, accuracy):
    await replay.run(scenario)
    assert replay.context.stub.requests == []
    facts = await chart(replay)
    assert facts["birth_time_accuracy"] == accuracy
    assert bool(facts["planets"]) == (accuracy == "exact")
    assert (facts["angles"] is not None) == (accuracy == "exact")
    async with replay.worker.database.transaction() as session:
        profile = await session.scalar(
            select(BirthProfile).where(BirthProfile.user_id == await replay.user_id())
        )
        assert b"1990-04-13" not in profile.encrypted_payload
    await replay.send(text="Explain my natal chart", contains="synthetic reflection")
    await replay.send(text="transits on 2026-10-02", contains="synthetic reflection")
    requests = [json.loads(r.content) for r in replay.context.stub.requests]
    assert len(requests) == 2
    assert requests[0]["metadata"]["session_id"] == requests[1]["metadata"]["session_id"]
    assert requests[0]["user"] == f"oria:{await replay.user_id()}"
    instructions = requests[1]["instructions"]
    assert '"birth_time_accuracy":"' + accuracy + '"' in instructions
    assert "2026-10-02" in instructions
    wire = json.dumps(requests)
    for excluded in ("1990-04-13", "Cluj-Napoca", "Europe/Bucharest", "synthetic_fixture"):
        assert excluded not in wire
    assert requests[0]["metadata"]["session_id"] not in replay.telegram.messages[-1]["text"]
    assert await count(replay, OnboardingProgress) == 0


async def test_ambiguous_place_requires_selection(replay):
    await replay.run("ambiguous-place")
    buttons = [
        b for row in replay.telegram.messages[-1]["reply_markup"]["inline_keyboard"] for b in row
    ]
    candidates = [b for b in buttons if b["text"].startswith("Portland")]
    assert len(candidates) >= 2
    assert await count(replay, BirthProfile) == 0
    assert await count(replay, AstrologyProfile) == 0
    selected = candidates[0]["text"]
    await replay.send(button=selected, contains="Please confirm")
    await replay.send(button="Confirm profile", contains="profile is active")
    async with replay.worker.database.transaction() as session:
        profile = await BirthProfileRepository(
            session, replay.worker.encryption, policy_version=replay.worker.flow.policy_version
        ).get(await replay.user_id())
        assert profile.birth_place.display_name in selected
        assert profile.birth_place.region in selected
    assert replay.context.stub.requests == []


async def test_decline_and_preconsent_input_never_reach_profile_or_context(replay):
    await replay.send(text="synthetic private birth values", contains="AI")
    await replay.send(button="Decline")
    await replay.send(text="1990-04-13")
    assert await count(replay, BirthProfile) == 0
    assert await count(replay, OnboardingProgress) == 0
    assert replay.context.stub.requests == []
    async with replay.worker.database.transaction() as session:
        assert (await session.scalar(select(Consent))).status == "declined"


async def test_duplicate_update_mutates_and_delivers_once(replay):
    await replay.send(text="/start")
    inbound = replay.update(button="agree")
    before = len(replay.telegram.messages)
    for _ in range(3):
        await replay.post(inbound)
    identifier = await replay.dispatch()
    await replay.worker.process(identifier)
    await replay.post(inbound)
    await replay.no_job()
    assert len(replay.telegram.messages) == before + 1
    assert await count(replay, Consent) == 1
    assert await count(replay, OnboardingProgress) == 1
    assert await count(replay, InboundEvent) == 2


async def test_profile_edit_invalidates_and_recalculates(replay):
    await replay.run("exact-time")
    original = await chart(replay)
    steps = scenario_steps("profile-edit")
    await replay.send(**steps[0])
    assert await chart(replay) is None
    for step in steps[1:]:
        await replay.send(**step)
    updated = await chart(replay)
    assert original["angles"] != updated["angles"]
    assert replay.context.stub.requests == []


async def test_input_output_and_high_stakes_policy(replay):
    await replay.run("exact-time")
    await replay.run("policy")
    replies = [r["text"] for r in replay.telegram.messages[-3:]]
    assert replies == [PRIVACY_REPLY, SAFETY_REPLY, PRIVACY_REPLY]
    assert replay.context.stub.requests == []
    replay.context.draft = "Tell me your email."
    await replay.send(text="Explain my chart", contains=PRIVACY_REPLY)
    assert len(replay.context.stub.requests) == 1
    # Local guarding does not promise to erase the draft from the owning service.
    assert (
        replay.context.transcripts[f"oria:{await replay.user_id()}"][0][1] == replay.context.draft
    )


async def test_deletion_purges_every_boundary_and_old_updates_stay_inert(replay):
    await replay.run("exact-time")
    await replay.send(text="Explain my chart")
    old_update = replay.last_update
    owner = await replay.user_id()
    subject = f"oria:{owner}"
    assert replay.context.transcripts[subject]
    async with replay.worker.database.transaction() as session:
        await replay.worker.flow.onboarding.context.remember(session, owner, "concise_readings")
    assert replay.context.stub.memories[subject]
    await replay.run("deletion")
    deletion = DeletionWorker(
        replay.worker.database,
        replay.worker.redis,
        replay.worker.encryption,
        replay.worker.flow.onboarding.context.provider,
        replay.worker.client,
    )
    await deletion.recover()
    assert replay.telegram.messages[-1]["text"] == FINAL_TEXT
    for model in (
        User,
        SocialIdentity,
        Consent,
        BirthProfile,
        AstrologyProfile,
        OnboardingProgress,
        ConversationSession,
    ):
        assert await count(replay, model) == 0
    assert subject in replay.context.stub.purged
    assert subject not in replay.context.transcripts
    assert subject not in replay.context.stub.memories
    assert subject not in replay.context.stub.sessions.values()
    assert await replay.worker.redis.get("oria:abuse:telegram:42:rate") is None
    async with replay.worker.database.transaction() as session:
        job = await session.scalar(select(DeletionJob))
        assert job.status == "completed" and job.encrypted_target is None
        receipts = list(await session.scalars(select(InboundEvent)))
        assert all(
            r.user_id is None and r.encrypted_input is None and r.encrypted_reply is None
            for r in receipts
        )
    with pytest.raises(ContextUnavailable):
        # Exercise the adapter against the remote tombstone without recreating a session.
        from uuid import uuid4

        from oria_engine.context.contracts import ContextScope, ConversationRequest

        await replay.worker.flow.onboarding.context.provider.respond(
            ContextScope(user_id=owner, session_id=uuid4()),
            ConversationRequest(filtered_message="Explain my chart"),
        )
    before = len(replay.telegram.messages)
    await replay.post(old_update)
    await replay.no_job()
    assert len(replay.telegram.messages) == before
    assert await replay.user_id() is None
    await replay.send(text="/start", contains="AI")
    assert await replay.user_id() != owner
    assert await count(replay, BirthProfile) == 0
    assert await count(replay, Consent) == 0


async def test_delivery_retry_reuses_committed_context_reply(replay):
    await replay.run("exact-time")
    replay.telegram.fail_sends = True
    await replay.post(replay.update(text="Explain my chart"))
    identifier = await replay.dispatch()
    async with replay.worker.database.transaction() as session:
        event = await session.get(InboundEvent, identifier)
        assert event.status == "ready" and event.encrypted_reply is not None
        event.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    assert len(replay.context.stub.requests) == 1
    replay.telegram.fail_sends = False
    await replay.worker.process(identifier)
    assert len(replay.context.stub.requests) == 1
    async with replay.worker.database.transaction() as session:
        event = await session.get(InboundEvent, identifier)
        assert event.status == "sent" and event.encrypted_reply is None


async def test_distinct_users_keep_distinct_context_sessions_and_replies(replay):
    for user in (42, 43):
        for step in scenario_steps("exact-time"):
            await replay.send(**step, user=user)
        await replay.send(text="Explain my chart", user=user)
    requests = [json.loads(r.content) for r in replay.context.stub.requests]
    assert len(requests) == 2
    assert requests[0]["user"] != requests[1]["user"]
    assert requests[0]["metadata"]["session_id"] != requests[1]["metadata"]["session_id"]
    for user, request in zip((42, 43), requests, strict=True):
        assert request["user"] == f"oria:{await replay.user_id(user)}"
    assert await count(replay, BirthProfile) == 2


async def test_context_http_outage_retries_without_sending_partial_reply(replay):
    await replay.run("exact-time")
    replay.context.fail_responses = True
    before = len(replay.telegram.messages)
    await replay.post(replay.update(text="Explain my chart"))
    identifier = await replay.dispatch()
    assert len(replay.telegram.messages) == before
    async with replay.worker.database.transaction() as session:
        event = await session.get(InboundEvent, identifier)
        assert event.status == "pending" and event.failure_code == "processing_failed"
        assert event.encrypted_reply is None and event.encrypted_input is not None
        event.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    replay.context.fail_responses = False
    await replay.worker.process(identifier)
    assert len(replay.telegram.messages) == before + 1
    assert len(replay.context.stub.requests) == 1
