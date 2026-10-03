"""Profile controls are owner-scoped local reads, including without current consent."""

import pytest

from oria_engine.db.models import BirthProfile, OnboardingProgress
from oria_engine.db.repositories import ConsentRepository
from oria_engine.domain.channel import HELP_TEXT
from oria_engine.domain.consent import ConsentFlow
from oria_engine.domain.onboarding import OnboardingFlow

from .test_astrology_profiles import chart_flow, confirm
from .test_onboarding import button, message, owner
from .test_onboarding import store as store


@pytest.mark.parametrize("time", ["03:42", "approximate 03:42", "unknown"])
async def test_inspection_and_withdrawal(store, encryption, birth_payload, time):
    flow, client = chart_flow(store, encryption, birth_payload)
    await confirm(flow, time)
    user = await owner(store)
    for withdrawn in (False, True):
        if withdrawn:
            await flow.handle(message(callback=flow.buttons[1].data))
        reply = await flow.handle(message("/profile"), command="profile")
        assert "1990-04-13" in reply.text
        assert ("unknown" if time == "unknown" else "03:42") in reply.text
        for value in (
            birth_payload.birth_place.city,
            birth_payload.birth_place.timezone,
            str(birth_payload.birth_place.latitude),
            str(birth_payload.birth_place.longitude),
        ):
            assert value in reply.text
        assert str(user) not in reply.text
        assert ("declined" if withdrawn else "accepted") in reply.text
        assert ("not current/available" if withdrawn else "current") in reply.text
    client.calculate_natal_chart.assert_awaited_once()
    other = await flow.handle(message("/profile", user="43"), command="profile")
    assert "No confirmed birth profile" in other.text and "1990-04-13" not in other.text


async def test_profile_inspection_does_not_start_setup_or_mutate_edits(
    store, encryption, birth_payload
):
    from sqlalchemy import select

    flow, client = chart_flow(store, encryption, birth_payload)
    await flow.handle(message("/profile"), command="profile")
    async with store.transaction() as session:
        assert await session.scalar(select(OnboardingProgress)) is None
        assert await session.scalar(select(BirthProfile)) is None
    await confirm(flow)
    edit = await flow.handle(message("/edit_profile"), command="edit_profile")
    edit = await flow.handle(message(callback=button(edit, "Edit date")))
    edit = await flow.handle(message("1991-04-13"))
    inspected = await flow.handle(message("/profile"), command="profile")
    assert "Confirmed birth profile" in inspected.text and "Unconfirmed draft" in inspected.text
    assert "1990-04-13" in inspected.text and "1991-04-13" in inspected.text
    assert "not current/available" in inspected.text
    # The inspection did not rotate the editor's callback token or confirm changes.
    await flow.handle(message(callback=button(edit, "Confirm profile")))
    inspected = await flow.handle(message("/profile"), command="profile")
    assert "1991-04-13" in inspected.text and "1990-04-13" not in inspected.text
    assert "Unconfirmed draft" not in inspected.text
    assert client.calculate_natal_chart.await_count == 2


async def test_help_privacy_and_changed_policy_are_read_only(store, encryption, birth_payload):
    flow, client = chart_flow(store, encryption, birth_payload)
    for accepted in (False, True):
        if accepted:
            await confirm(flow)
        user = await owner(store) if accepted else None
        assert (await flow.handle(message("/help"), command="help")).text == HELP_TEXT
        privacy = await flow.handle(message("/privacy"), command="privacy")
        assert "SecondContext" in privacy.text and "Deletion" in privacy.text
        assert privacy.buttons == flow.buttons
        if user:
            async with store.transaction() as session:
                assert await ConsentRepository(session).current(user, "v1") is not None
    changed = ConsentFlow(
        store, "v2", OnboardingFlow(encryption, "v2", flow.onboarding.resolver, client)
    )
    inspected = await changed.handle(message("/profile"), command="profile")
    assert "Current policy: v2" in inspected.text and "accepted (policy v1)" in inspected.text
    assert "1990-04-13" in inspected.text and "not current/available" in inspected.text
    client.calculate_natal_chart.assert_awaited_once()


async def test_place_and_clock_occurrence_can_be_inspected_and_corrected(
    store, encryption, birth_payload
):
    flow, client = chart_flow(store, encryption, birth_payload)
    await confirm(flow)
    edit = await flow.handle(message("/edit_profile"), command="edit_profile")
    edit = await flow.handle(message(callback=button(edit, "Edit place")))
    place = birth_payload.birth_place.model_copy(
        update={
            "display_name": "Bucharest, Romania",
            "city": "Bucharest",
            "region": "Bucharest",
            "latitude": 44.43,
            "longitude": 26.1,
        }
    )
    flow.onboarding.resolver.resolve.return_value = (place,)
    edit = await flow.handle(message("Bucharest, Romania"))
    edit = await flow.handle(message(callback=edit.buttons[0].data))
    edit = await flow.handle(message(callback=button(edit, "Edit date")))
    edit = await flow.handle(message("2020-10-25"))
    edit = await flow.handle(message(callback=edit.buttons[1].data))  # Second clock occurrence.
    await flow.handle(message(callback=button(edit, "Confirm profile")))
    inspected = await flow.handle(message("/profile"), command="profile")
    assert "Bucharest" in inspected.text and "44.43, 26.1" in inspected.text
    assert "Clock-change occurrence: second" in inspected.text
    assert "Cluj" not in inspected.text
    edit = await flow.handle(message("/edit_profile"), command="edit_profile")
    edit = await flow.handle(message(callback=button(edit, "Edit time")))
    edit = await flow.handle(message("unknown"))
    await flow.handle(message(callback=button(edit, "Confirm profile")))
    inspected = await flow.handle(message("/profile"), command="profile")
    assert "Clock-change occurrence" not in inspected.text and "unknown" in inspected.text
    assert client.calculate_natal_chart.await_count == 3
