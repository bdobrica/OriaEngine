"""Derived cache lifecycle with synthetic data and real isolated PostgreSQL."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from astrology_mcp.engine import calculate
from sqlalchemy import select

from oria_engine.astrology.client import AstrologyUnavailable
from oria_engine.db.astrology_profiles import AstrologyProfileRepository
from oria_engine.db.birth_profiles import BirthProfileRepository, ConsentRequiredError
from oria_engine.db.models import AstrologyProfile, BirthProfile
from oria_engine.db.repositories import ConsentRepository
from oria_engine.domain.consent import ConsentFlow
from oria_engine.domain.consent import OnboardingState as State
from oria_engine.domain.onboarding import OnboardingFlow

from .test_onboarding import button, message, owner, setup_to_time
from .test_onboarding import store as store  # Reuse isolated cleanup fixture.


def chart_flow(store, encryption, birth_payload):
    client = AsyncMock()
    client.calculate_natal_chart.side_effect = calculate
    resolver = AsyncMock()
    resolver.resolve.return_value = (birth_payload.birth_place,)
    flow = ConsentFlow(store, "v1", OnboardingFlow(encryption, "v1", resolver, client))
    return flow, client


async def confirm(flow, time="03:42"):
    await setup_to_time(flow)
    await flow.handle(message(time))
    reply = await flow.handle(message("Cluj-Napoca, Romania"))
    reply = await flow.handle(message(callback=reply.buttons[0].data))
    return await flow.handle(message(callback=button(reply, "Confirm profile")))


@pytest.mark.parametrize("time", ["03:42", "approximate 03:42", "unknown"])
async def test_confirm_cache_isolation_and_versions(store, encryption, birth_payload, time):
    flow, client = chart_flow(store, encryption, birth_payload)
    assert (await confirm(flow, time)).state == State.ACTIVE
    user = await owner(store)
    assert client.calculate_natal_chart.call_count == 1
    request = client.calculate_natal_chart.call_args.args[0]
    assert "user_id" not in request.model_dump()
    assert (request.timestamp_utc is None) == (time == "unknown")
    assert (await flow.handle(message("/profile"), command="profile")).state == State.ACTIVE
    assert client.calculate_natal_chart.call_count == 1
    async with store.transaction() as session:
        repo = AstrologyProfileRepository(session, policy_version="v1")
        result = await repo.get(user)
        assert result is not None
        assert await repo.get(uuid4()) is None
        row = await session.get(AstrologyProfile, user)
        assert row.source_profile_id is not None and row.source_schema_version == 2
        assert "birth_date" not in row.result and "timestamp_utc" not in row.result
        row.calculation_versions = {**row.calculation_versions, "engine_version": "old"}
    assert (
        await flow.handle(message("/profile"), command="profile")
    ).state == State.COMPUTING_PROFILE
    assert client.calculate_natal_chart.call_count == 1
    client.calculate_natal_chart.side_effect = AstrologyUnavailable("synthetic-private")
    reply = await flow.handle(message("/retry_profile"), command="retry_profile")
    assert "synthetic-private" not in reply.text and "/retry_profile" in reply.text
    async with store.transaction() as session:
        row = await session.get(AstrologyProfile, user)
        assert row.calculation_versions["engine_version"] == "old"  # Failure preserves old state.
        assert await session.scalar(select(BirthProfile)) is not None
    client.calculate_natal_chart.side_effect = calculate
    assert (
        await flow.handle(message("/retry_profile"), command="retry_profile")
    ).state == State.ACTIVE
    async with store.transaction() as session:
        row = await session.get(AstrologyProfile, user)
        row.calculation_versions = {**row.calculation_versions, "timezone_version": "old"}
    assert (
        await flow.handle(message("/profile"), command="profile")
    ).state == State.COMPUTING_PROFILE


async def test_failure_restart_edit_and_recompute(store, encryption, birth_payload):
    flow, client = chart_flow(store, encryption, birth_payload)
    client.calculate_natal_chart.side_effect = AstrologyUnavailable()
    assert (await confirm(flow)).state == State.COMPUTING_PROFILE
    user = await owner(store)
    async with store.transaction() as session:
        assert await session.get(AstrologyProfile, user) is None
        assert await session.scalar(select(BirthProfile)) is not None
    flow, client = chart_flow(store, encryption, birth_payload)
    assert (
        await flow.handle(message("/retry_profile"), command="retry_profile")
    ).state == State.ACTIVE
    reply = await flow.handle(message("/edit_profile"), command="edit_profile")
    async with store.transaction() as session:
        assert await session.get(AstrologyProfile, user) is None
    reply = await flow.handle(message(callback=button(reply, "Edit time")))
    assert reply.state == State.BIRTH_TIME_REQUIRED
    reply = await flow.handle(message("unknown"))
    reply = await flow.handle(message(callback=button(reply, "Confirm profile")))
    assert reply.state == State.ACTIVE and "unavailable" in reply.text
    assert client.calculate_natal_chart.call_count == 2
    async with store.transaction() as session:
        profiles = BirthProfileRepository(session, encryption, policy_version="v1")
        await profiles.save(user, birth_payload)
        assert await session.get(AstrologyProfile, user) is None


async def test_consent_and_concurrent_calculation(store, encryption, birth_payload):
    flow, client = chart_flow(store, encryption, birth_payload)
    client.calculate_natal_chart.side_effect = AstrologyUnavailable()
    await confirm(flow)
    user = await owner(store)
    client.calculate_natal_chart.reset_mock()
    client.calculate_natal_chart.side_effect = calculate
    replies = await asyncio.gather(
        *[flow.handle(message("/retry_profile"), command="retry_profile") for _ in range(2)]
    )
    assert all(r.state == State.ACTIVE for r in replies)
    assert client.calculate_natal_chart.call_count == 1
    async with store.transaction() as session:
        await ConsentRepository(session).decline(user, "v1", "telegram")
    async with store.transaction() as session:
        repo = AstrologyProfileRepository(session, policy_version="v1")
        assert await repo.get(user) is None
        with pytest.raises(ConsentRequiredError):
            await repo.calculate(
                user, BirthProfileRepository(session, encryption, policy_version="v1"), client
            )
    assert client.calculate_natal_chart.call_count == 1


async def test_legacy_overlap_requires_confirmation(store, encryption, birth_payload):
    flow, client = chart_flow(store, encryption, birth_payload)
    await flow.handle(message(callback=flow.buttons[0].data))
    user = await owner(store)
    from oria_engine.db.onboarding import OnboardingRepository
    from oria_engine.domain.birth_profile import BirthProfilePayload

    payload = BirthProfilePayload.model_validate(
        {
            **birth_payload.model_dump(mode="json"),
            "schema_version": 1,
            "birth_date": "2020-10-25",
            "birth_local_time": "03:30:00",
        }
    )
    async with store.transaction() as session:
        await OnboardingRepository(session, encryption, "v1").clear(user)
        await BirthProfileRepository(session, encryption, policy_version="v1").save(user, payload)
    reply = await flow.handle(message("/retry_profile"), command="retry_profile")
    assert reply.state == State.BIRTH_TIME_CLARIFICATION
    assert client.calculate_natal_chart.call_count == 0
    reply = await flow.handle(message(callback=reply.buttons[0].data))
    assert reply.state == State.PROFILE_CONFIRMATION
    reply = await flow.handle(message(callback=button(reply, "Confirm profile")))
    assert reply.state == State.ACTIVE
