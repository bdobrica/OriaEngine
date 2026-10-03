"""Synthetic provider and real queue/storage: complete guarded conversation path."""

from unittest.mock import AsyncMock, patch

import pytest
from astrology_mcp.engine import calculate, calculate_transits
from sqlalchemy import delete

from oria_engine.astrology.client import AstrologyUnavailable
from oria_engine.context.contracts import ContextReply, ContextUnavailable
from oria_engine.context.service import ConversationContext
from oria_engine.db.birth_profiles import BirthProfileRepository
from oria_engine.db.models import BirthProfile, User
from oria_engine.domain.onboarding import OnboardingFlow
from oria_engine.domain.policy import PRIVACY_REPLY, SAFETY_REPLY

from .test_astrology_profiles import confirm
from .test_queue import due, message, row
from .test_queue import queue as queue


@pytest.fixture
async def conversation(queue, birth_payload):
    ingress, worker = queue
    astrology = AsyncMock()
    astrology.calculate_natal_chart.side_effect = calculate
    astrology.calculate_transits.side_effect = calculate_transits
    provider = AsyncMock()
    provider.respond.return_value = ContextReply(
        response_id="synthetic", text="A reflective reply."
    )
    resolver = AsyncMock()
    resolver.resolve.return_value = (birth_payload.birth_place,)
    worker.flow.onboarding = OnboardingFlow(
        worker.encryption,
        worker.flow.policy_version,
        resolver,
        astrology,
        ConversationContext(provider, worker.flow.policy_version),
    )
    return ingress, worker, astrology, provider


async def test_complete_queued_onboarding_and_conversation(conversation):
    ingress, worker, astrology, provider = conversation

    async def send(text="", callback=None, command=None):
        identifier = await ingress.accept(message(text=text, callback=callback), command=command)
        await worker.process(identifier)
        assert (await row(worker, identifier)).status == "sent"
        return worker.client.send_text.call_args

    await send(command="start")
    await send(callback=worker.flow.buttons[0].data)
    await send("1990-04-13")
    await send("03:42")
    result = await send("Cluj-Napoca, Romania")
    result = await send(callback=result.kwargs["buttons"][0].data)
    button = next(b for b in result.kwargs["buttons"] if b.text == "Confirm profile")
    await send(callback=button.data)
    provider.respond.assert_not_called()
    with patch.object(BirthProfileRepository, "get", side_effect=AssertionError("No decrypt")):
        await send("Explain my natal chart")
        scope, request = provider.respond.call_args.args
        assert request.natal_facts is not None and request.transit_facts is None
        assert "1990-04-13" not in request.model_dump_json()
        await send("Tell me more")
        assert provider.respond.call_args.args[0] == scope
        assert provider.respond.call_args.args[1].natal_facts == request.natal_facts
        await send("transits on 2026-10-02")
        assert provider.respond.call_args.args[1].transit_facts is not None
    astrology.calculate_natal_chart.assert_awaited_once()
    astrology.calculate_transits.assert_awaited_once()


@pytest.mark.parametrize("dependency", ["astrology", "context"])
async def test_dependency_failure_retries_then_send_reuses_reply(conversation, dependency):
    ingress, worker, astrology, provider = conversation
    await confirm(worker.flow)
    target = astrology.calculate_transits if dependency == "astrology" else provider.respond
    target.side_effect = (
        AstrologyUnavailable() if dependency == "astrology" else ContextUnavailable()
    )
    identifier = await ingress.accept(message(text="today"))
    await worker.process(identifier)
    event = await row(worker, identifier)
    assert event.status == "pending" and event.failure_code == "processing_failed"
    assert event.encrypted_input and not event.encrypted_reply
    worker.client.send_text.assert_not_called()
    target.side_effect = calculate_transits if dependency == "astrology" else None
    worker.client.send_text.side_effect = RuntimeError("synthetic send failure")
    await due(worker, identifier)
    await worker.process(identifier)
    assert (await row(worker, identifier)).status == "ready"
    count = provider.respond.await_count
    worker.client.send_text.side_effect = None
    await due(worker, identifier)
    await worker.process(identifier)
    assert (await row(worker, identifier)).status == "sent"
    assert provider.respond.await_count == count


@pytest.mark.parametrize(
    "text,expected",
    [
        ("My email is synthetic@example.invalid", PRIVACY_REPLY),
        ("Will I die today?", SAFETY_REPLY),
        ("transits tomorrow", "YYYY-MM-DD"),
    ],
)
async def test_local_boundaries_never_call_context(conversation, text, expected):
    ingress, worker, astrology, provider = conversation
    await confirm(worker.flow)
    await worker.process(await ingress.accept(message(text=text)))
    assert expected in worker.client.send_text.call_args.args[1]
    provider.respond.assert_not_called()
    astrology.calculate_transits.assert_not_called()


async def test_guarded_output_and_length(conversation):
    ingress, worker, _, provider = conversation
    await confirm(worker.flow)
    provider.respond.return_value = ContextReply(
        response_id="synthetic", text="Tell me your email."
    )
    await worker.process(await ingress.accept(message(text="Tell me more")))
    assert worker.client.send_text.call_args.args[1] == PRIVACY_REPLY
    provider.respond.return_value = ContextReply(response_id="synthetic", text="🌙" * 3000)
    await worker.process(await ingress.accept(message(text="Tell me more")))
    assert "too long" in worker.client.send_text.call_args.args[1]


@pytest.mark.parametrize("delete_user", [False, True])
async def test_deletion_before_queued_chat_rechecks_current_state(conversation, delete_user):
    ingress, worker, _, provider = conversation
    await confirm(worker.flow)
    identifier = await ingress.accept(message(text="Explain my chart"))
    user_id = (await row(worker, identifier)).user_id
    async with worker.database.transaction() as session:
        if delete_user:
            from datetime import UTC, datetime

            user = await session.get(User, user_id)
            user.deleted_at = datetime.now(UTC)
        else:
            await session.execute(delete(BirthProfile).where(BirthProfile.user_id == user_id))
    await worker.process(identifier)
    provider.respond.assert_not_called()
    assert (await row(worker, identifier)).status == ("dead" if delete_user else "sent")


@pytest.mark.parametrize("accuracy", ["unknown", "approximate 03:42"])
async def test_uncertainty_reaches_context(conversation, accuracy):
    ingress, worker, _, provider = conversation
    await confirm(worker.flow, accuracy)
    await worker.process(await ingress.accept(message(text="today")))
    request = provider.respond.call_args.args[1]
    assert request.natal_facts.birth_time_accuracy == accuracy.split()[0]
    assert request.transit_facts.birth_time_accuracy == accuracy.split()[0]
    if accuracy == "unknown":
        assert not request.natal_facts.planets and request.natal_facts.angles is None
        assert not request.transit_facts.aspects


async def test_consent_withdrawal_before_processing_prevents_context(conversation):
    from oria_engine.db.repositories import ConsentRepository

    ingress, worker, _, provider = conversation
    await confirm(worker.flow)
    identifier = await ingress.accept(message(text="Explain my chart"))
    user_id = (await row(worker, identifier)).user_id
    async with worker.database.transaction() as session:
        await ConsentRepository(session).revoke(user_id, "telegram")
    await worker.process(identifier)
    provider.respond.assert_not_called()
    assert (await row(worker, identifier)).status == "sent"


async def test_worker_through_http_adapter(conversation):
    import json

    import httpx

    from oria_engine.config import Settings
    from oria_engine.context.second_context import SecondContextProvider
    from tests.support.second_context import SecondContextStub

    ingress, worker, _, _ = conversation
    stub = SecondContextStub(namespace="oria", token="synthetic-test-token")
    provider = SecondContextProvider(
        Settings(
            _env_file=None,
            second_context_subject_namespace="oria",
            second_context_bearer_token="synthetic-test-token",
        ),
        transport=httpx.MockTransport(stub),
    )
    worker.flow.onboarding.context = ConversationContext(provider, worker.flow.policy_version)
    try:
        await confirm(worker.flow)
        await worker.process(await ingress.accept(message(text="Explain my natal chart")))
        body = json.loads(stub.requests[0].content)
        assert body["input"] == "Explain my natal chart"
        assert "1990-04-13" not in stub.requests[0].content.decode()
        assert "Cluj" not in stub.requests[0].content.decode()
        assert "instructions" in body and body["user"].startswith("oria:")
        assert worker.client.send_text.call_args.args[1] == "No prior preference."
    finally:
        await provider.aclose()


async def test_profile_reply_is_encrypted_reused_and_never_sent_to_context(conversation):
    ingress, worker, astrology, provider = conversation
    await confirm(worker.flow)
    worker.client.send_text.side_effect = RuntimeError("synthetic send failure")
    identifier = await ingress.accept(message(text="/profile"), command="profile")
    await worker.process(identifier)
    event = await row(worker, identifier)
    assert event.status == "ready" and event.encrypted_reply
    assert b"1990-04-13" not in event.encrypted_reply
    reply = worker.client.send_text.call_args.args[1]
    assert "1990-04-13" in reply
    worker.client.send_text.side_effect = None
    await due(worker, identifier)
    with patch.object(BirthProfileRepository, "get", side_effect=AssertionError("No reread")):
        await worker.process(identifier)
    assert worker.client.send_text.call_args.args[1] == reply
    assert (await row(worker, identifier)).encrypted_reply is None
    provider.respond.assert_not_called()
    astrology.calculate_natal_chart.assert_awaited_once()


async def test_queued_inspection_after_withdrawal(conversation):
    from oria_engine.db.repositories import ConsentRepository

    ingress, worker, astrology, provider = conversation
    await confirm(worker.flow)
    await worker.flow.handle(message(callback=worker.flow.buttons[1].data))
    identifier = await ingress.accept(message(text="/profile"), command="profile")
    await worker.process(identifier)
    event = await row(worker, identifier)
    assert event.status == "sent"
    reply = worker.client.send_text.call_args.args[1]
    assert "1990-04-13" in reply and "declined" in reply
    assert "not current/available" in reply
    await worker.process(
        await ingress.accept(message(text="/edit_profile"), command="edit_profile")
    )
    assert "stopped" in worker.client.send_text.call_args.args[1]
    async with worker.database.transaction() as session:
        assert (
            await ConsentRepository(session).current(event.user_id, worker.flow.policy_version)
            is None
        )
    provider.respond.assert_not_called()
    astrology.calculate_natal_chart.assert_awaited_once()
