"""HTTP consumer validation; upstream dependency-backed evidence is separate."""

import json
from uuid import uuid4

import httpx
import pytest

from oria_engine.config import Settings
from oria_engine.context.contracts import ContextUnavailable
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.knowledge.contracts import (
    ContextProjection,
    ProjectionDelete,
    ProjectionUpsert,
    RecordRef,
)

SUBJECT = "oria:11111111-1111-4111-8111-111111111111"


def client(handler):
    return SecondContextProvider(
        Settings(
            _env_file=None,
            second_context_subject_namespace="oria",
            second_context_bearer_token="synthetic-token",
            second_context_knowledge_enabled=True,
        ),
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"user": "oria:22222222-2222-4222-8222-222222222222"},
        {"operation_id": str(uuid4())},
        {"operation": "upsert"},
        {"coverage": "projection_and_indexes"},
        {"status": "pending"},
        {"unknown": "escape hatch"},
        {"record": {"kind": "event", "id": str(uuid4()), "revision": 2}},
    ],
)
async def test_delete_acknowledgements_must_match_exact_scope_operation_revision_and_coverage(
    change,
):
    request = ProjectionDelete(
        user=SUBJECT, operation_id=uuid4(), record=RecordRef(kind="event", id=uuid4(), revision=2)
    )

    def handler(incoming):
        body = json.loads(incoming.content)
        assert incoming.headers["X-SecondContext-Subject"] == SUBJECT
        return httpx.Response(
            200,
            json={
                **body,
                "status": "completed",
                "coverage": "active_stores_and_linked_history",
                **change,
            },
        )

    p = client(handler)
    try:
        with pytest.raises(ContextUnavailable):
            await p.project(request)
    finally:
        await p.aclose()


async def test_lost_ack_is_retryable_with_identical_operation_body():
    ref = RecordRef(kind="event", id=uuid4(), revision=1)
    request = ProjectionUpsert(
        user=SUBJECT,
        operation_id=uuid4(),
        projection=ContextProjection(
            record=ref,
            label="wedding",
            summary="A described wedding.",
            knowledge_kind="user_statement",
            sources=(ref,),
        ),
    )
    calls = []

    def handler(incoming):
        body = json.loads(incoming.content)
        calls.append(body)
        if len(calls) == 1:
            raise httpx.ReadTimeout("synthetic")
        return httpx.Response(
            200,
            json={
                "contract_version": 1,
                "operation": "upsert",
                "user": SUBJECT,
                "operation_id": body["operation_id"],
                "record": body["projection"]["record"],
                "status": "completed",
                "coverage": "projection_and_indexes",
            },
        )

    p = client(handler)
    try:
        with pytest.raises(ContextUnavailable):
            await p.project(request)
        assert len(calls) == 1
        await p.project(request)
        assert calls[0] == calls[1]
    finally:
        await p.aclose()


@pytest.mark.parametrize(
    "body",
    [
        {"status": "ok"},
        {
            "contract_version": 1,
            "user": SUBJECT,
            "implementation": "linked-context-1",
            "history_coverage": "index_only",
            "index": "postgres",
            "status": "ready",
        },
    ],
)
async def test_health_or_partial_coverage_is_not_capability_evidence(body):
    p = client(lambda request: httpx.Response(200, json=body))
    try:
        with pytest.raises(ContextUnavailable):
            await p.projection_capabilities(uuid4())
    finally:
        await p.aclose()
