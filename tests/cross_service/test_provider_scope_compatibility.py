"""Every provider response path must preserve the authenticated subject echo."""

from uuid import uuid4

import pytest

from oria_engine.context.contracts import ContextScope, ConversationRequest


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
