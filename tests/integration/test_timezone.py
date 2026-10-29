"""Current timezone is explicit, owner-scoped and independent of birth/chart state."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import patch

from astrology_mcp.engine import calculate_transits
from sqlalchemy import select

from oria_engine.db.birth_profiles import BirthProfileRepository
from oria_engine.db.models import User
from oria_engine.domain.consent import OnboardingState as State

from .test_astrology_profiles import chart_flow, confirm
from .test_onboarding import message, owner
from .test_onboarding import store as store


async def test_timezone_requires_consent_and_cannot_select_another_owner(
    store, encryption, birth_payload
):
    flow, client = chart_flow(store, encryption, birth_payload)
    client.calculate_transits.side_effect = calculate_transits
    assert (
        await flow.handle(message("/timezone UTC"), command="timezone")
    ).state == State.CONSENT_REQUIRED
    await confirm(flow)
    assert "/timezone" in (await flow.handle(message("tomorrow"))).text
    await flow.handle(message("/timezone Europe/Bucharest"), command="timezone")
    assert "Europe/Bucharest" in (await flow.handle(message("/profile"), command="profile")).text
    assert client.calculate_natal_chart.await_count == 1
    await flow.handle(message(callback=flow.buttons[0].data, user="43"))
    assert (
        "not set" in (await flow.handle(message("/timezone", user="43"), command="timezone")).text
    )
    async with store.transaction() as session:
        zones = list(await session.scalars(select(User.current_timezone)))
        assert sorted(zone or "" for zone in zones) == ["", "Europe/Bucharest"]
    with patch.object(BirthProfileRepository, "get", side_effect=AssertionError("No decrypt")):
        incoming = replace(
            message("How will tomorrow be at work?"),
            received_at=datetime(2026, 10, 29, 23, 30, tzinfo=UTC),
        )
        reply = await flow.handle(incoming)
        assert "2026-10-31 10:00:00 UTC" in reply.text
    await flow.handle(message("/timezone clear"), command="timezone")
    assert "/timezone" in (await flow.handle(message("tomorrow"))).text
    assert client.calculate_natal_chart.await_count == 1
    await flow.handle(message(callback=flow.buttons[1].data))
    await flow.handle(message("/timezone UTC"), command="timezone")
    async with store.transaction() as session:
        assert (await session.get(User, await owner(store))).current_timezone is None


async def test_invalid_timezone_cannot_overwrite_preference(store, encryption, birth_payload):
    flow, _ = chart_flow(store, encryption, birth_payload)
    await confirm(flow)
    await flow.handle(message("/timezone UTC"), command="timezone")
    for invalid in ["Mars/Olympus", "../secret", "Europe/Bucharest extra"]:
        await flow.handle(message("/timezone " + invalid), command="timezone")
    reply = await flow.handle(message("/timezone"), command="timezone")
    assert "Current timezone: UTC." in reply.text
