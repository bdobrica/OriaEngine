"""Active routing behind real consent/profile gates; no provider or user data."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from astrology_mcp.engine import calculate_transits

from oria_engine.astrology.client import AstrologyUnavailable
from oria_engine.db.birth_profiles import BirthProfileRepository
from oria_engine.domain.consent import OnboardingState as State

from .test_astrology_profiles import chart_flow, confirm
from .test_onboarding import message
from .test_onboarding import store as store


async def test_active_fact_routing_without_decrypting(store, encryption, birth_payload):
    flow, client = chart_flow(store, encryption, birth_payload)
    client.calculate_transits.side_effect = calculate_transits
    await confirm(flow)
    with patch.object(BirthProfileRepository, "get", side_effect=AssertionError("No decrypt")):
        reply = await flow.handle(message("Explain my natal chart"))
        assert reply.state == State.ACTIVE and "Your saved natal chart" in reply.text
        client.calculate_transits.assert_not_called()
        ambiguous = await flow.handle(message("transits on 04/05/2026"))
        assert "YYYY-MM-DD" in ambiguous.text
        client.calculate_transits.assert_not_called()
        high_stakes = await flow.handle(message("Will I die today?"))
        assert "high-stakes" in high_stakes.text
        client.calculate_transits.assert_not_called()
        follow_up = await flow.handle(message("Tell me more"))
        assert "restate the topic" in follow_up.text
        client.calculate_transits.assert_not_called()
        incoming = message("today")
        reply = await flow.handle(incoming)
        assert "Transit snapshot" in reply.text
        assert (
            client.calculate_transits.call_args.args[0].target_timestamp_utc == incoming.received_at
        )
        reply = await flow.handle(message("2026-10-02"))
        assert "2026-10-02 12:00:00 UTC" in reply.text
        assert client.calculate_transits.call_args.args[0].target_timestamp_utc == datetime(
            2026, 10, 2, 12, tzinfo=UTC
        )
    assert client.calculate_natal_chart.call_count == 1
    assert "1990-04-13" not in reply.text and "Cluj" not in reply.text


@pytest.mark.parametrize("time", ["unknown", "approximate 03:42"])
async def test_active_uncertainty_and_recoverable_failure(store, encryption, birth_payload, time):
    flow, client = chart_flow(store, encryption, birth_payload)
    await confirm(flow, time)
    client.calculate_transits.side_effect = AstrologyUnavailable("synthetic-private")
    reply = await flow.handle(message("today"))
    assert reply.state == State.ACTIVE and "temporarily unavailable" in reply.text
    assert "synthetic-private" not in reply.text
    client.calculate_transits.side_effect = calculate_transits
    reply = await flow.handle(message("today"))
    assert "unknown" in reply.text if time == "unknown" else "approximate" in reply.text
    if time == "unknown":
        assert "not personalized" in reply.text
        assert not client.calculate_transits.call_args.args[0].natal_positions


async def test_no_active_calculation_before_consent_or_during_edits(
    store, encryption, birth_payload
):
    flow, client = chart_flow(store, encryption, birth_payload)
    client.calculate_transits = AsyncMock(side_effect=AssertionError("Not active"))
    assert (await flow.handle(message("today"))).state == State.CONSENT_REQUIRED
    await confirm(flow)
    # Another identity cannot select this user's cache.
    assert (await flow.handle(message("today", user="43"))).state == State.CONSENT_REQUIRED
    await flow.handle(message(callback=flow.buttons[1].data))
    assert (await flow.handle(message("today"))).state == State.CLOSED
    await flow.handle(message(callback=flow.buttons[0].data))
    await flow.handle(message("/edit_profile"), command="edit_profile")
    assert (await flow.handle(message("today"))).state == State.PROFILE_CONFIRMATION
    client.calculate_transits.assert_not_called()
