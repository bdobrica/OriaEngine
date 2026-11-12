"""Every provider response path must preserve the authenticated subject echo."""

import json
from uuid import uuid4

import pytest

from oria_engine.context.contracts import ContextScope, ConversationRequest
from oria_engine.context.history import AcceptGenerated


@pytest.mark.parametrize(
    "message",
    ["Suggest a quiet activity", "Pause learning", "Can you show my memories?"],
)
async def test_managed_response_paths_preserve_subject_scope(real_history, message):
    _, worker, _, _, _, user_id = real_history
    provider = worker.history_provider
    scope = ContextScope(user_id=user_id, session_id=uuid4())
    prepared = provider.prepare_history_turn(
        scope, ConversationRequest(filtered_message=message), turn_id=uuid4()
    )

    draft = await provider.respond_history(scope, prepared)

    assert draft.user == provider.subject(user_id)
    assert draft.session_id == str(scope.session_id)
    assert draft.turn_id == prepared.turn_id


async def test_interpretation_uses_accepted_dialogue_within_its_session(real_history):
    _, worker, model, _, _, user_id = real_history
    provider = worker.history_provider
    scope = ContextScope(user_id=user_id, session_id=uuid4())
    first = provider.prepare_history_turn(
        scope, ConversationRequest(filtered_message="Suggest two activities"), turn_id=uuid4()
    )
    draft = await provider.respond_history(scope, first)
    replacement = "First, read a book. Second, take a walk."
    await provider.finalize_history(
        scope,
        AcceptGenerated(
            contract_version=1,
            user=provider.subject(user_id),
            session_id=str(scope.session_id),
            turn_id=first.turn_id,
            action="accept_generated",
            response_id=draft.response_id,
            assistant_text=replacement,
        ),
    )
    followup = provider.prepare_history_turn(
        scope, ConversationRequest(filtered_message="The second one"), turn_id=uuid4()
    )
    await provider.respond_history(scope, followup)
    assert json.loads(model.interpretations[-1]["messages"][-1]["content"]) == [
        {"role": "user", "content": "Suggest two activities"},
        {"role": "assistant", "content": replacement},
        {"role": "user", "content": "The second one"},
    ]

    separate = ContextScope(user_id=user_id, session_id=uuid4())
    request = provider.prepare_history_turn(
        separate, ConversationRequest(filtered_message="Explain rainbows"), turn_id=uuid4()
    )
    await provider.respond_history(separate, request)
    assert json.loads(model.interpretations[-1]["messages"][-1]["content"]) == [
        {"role": "user", "content": "Explain rainbows"}
    ]
