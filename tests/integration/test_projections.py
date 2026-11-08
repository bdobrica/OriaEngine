"""Durable encrypted outbox and strict HTTP consumer lifecycle; not upstream evidence."""

import json
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from oria_engine.config import Settings
from oria_engine.context.projections import LinkedContext, recover_projections
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.context.service import ConversationContext
from oria_engine.db.birth_profiles import BirthProfileRepository
from oria_engine.db.models import ContextProjectionWork
from oria_engine.db.repositories import ConsentRepository
from oria_engine.knowledge.contracts import EntityRecord

from .test_knowledge import active, message
from .test_onboarding import store as store
from .test_temporal import clear_context as clear_context


class ProjectionService:
    """Wire stub with revision/idempotency fences; real service has its own tests."""

    def __init__(self):
        self.records = {}
        self.operations = {}
        self.fail = False
        self.calls = []

    def __call__(self, request):
        body = json.loads(request.content)
        self.calls.append((request.url.path, body))
        assert request.headers["X-SecondContext-Subject"] == body["user"]
        if self.fail:
            return httpx.Response(503)
        if request.url.path.endswith("capabilities"):
            return httpx.Response(
                200,
                json={
                    "contract_version": 1,
                    "user": body["user"],
                    "implementation": "linked-context-1",
                    "history_coverage": "linked_sessions",
                    "index": "postgres",
                    "status": "ready",
                },
            )
        operation = body.get("operation")
        if operation in {"upsert", "delete"}:
            ref = body["projection"]["record"] if operation == "upsert" else body["record"]
            key = (body["user"], ref["id"])
            op_key = (body["user"], body["operation_id"])
            if op_key in self.operations and self.operations[op_key] != body:
                return httpx.Response(409)
            self.operations[op_key] = body
            old = self.records.get(key)
            if old and (
                old["deleted"] and operation == "upsert" or old["revision"] > ref["revision"]
            ):
                return httpx.Response(409)
            self.records[key] = {
                "revision": ref["revision"],
                "deleted": operation == "delete",
                "projection": body.get("projection"),
            }
            return httpx.Response(
                200,
                json={
                    "contract_version": 1,
                    "user": body["user"],
                    "operation": operation,
                    "operation_id": body["operation_id"],
                    "record": ref,
                    "status": "completed",
                    "coverage": "active_stores_and_linked_history"
                    if operation == "delete"
                    else "projection_and_indexes",
                },
            )
        if operation == "query":
            matches = [
                r["projection"]
                for (user, _), r in self.records.items()
                if user == body["user"] and not r["deleted"]
            ]
            return httpx.Response(
                200,
                json={
                    "contract_version": 1,
                    "operation": "query",
                    "user": body["user"],
                    "matches": matches[: body["limit"]],
                },
            )
        if request.url.path.endswith("responses"):
            return httpx.Response(
                200,
                json={
                    "id": "response-synthetic",
                    "object": "response",
                    "status": "completed",
                    "output_text": "Your shared relationship themes suggest room for cooperation.",
                    "metadata": {
                        "session_id": body["metadata"]["session_id"],
                        "context_packet": {"user_external_id": body["user"]},
                    },
                },
            )
        return httpx.Response(404)


def provider(service):
    return SecondContextProvider(
        Settings(
            _env_file=None,
            second_context_subject_namespace="oria",
            second_context_bearer_token="synthetic-service",
            second_context_knowledge_enabled=True,
        ),
        transport=httpx.MockTransport(service),
    )


async def prepare(store, encryption, birth_payload):
    flow, client, old, user_id = await active(store, encryption, birth_payload)
    remote = ProjectionService()
    p = provider(remote)
    flow.onboarding.context = ConversationContext(p, "v1")
    return flow, p, remote, user_id


async def test_save_reconcile_recall_interpretation_and_selective_delete(
    store, encryption, birth_payload
):
    flow, p, remote, user_id = await prepare(store, encryption, birth_payload)
    try:
        assert "Saved" in (await flow.handle(message("My girlfriend is Alice"))).text
        assert "Saved" in (await flow.handle(message("Her birthday is June 2nd, 1992"))).text
        assert not remote.calls  # Outbox commits before any remote mutation.
        async with store.transaction() as session:
            rows = list(await session.scalars(select(ContextProjectionWork)))
            assert rows and all(b"Alice" not in r.encrypted_payload for r in rows)
        await recover_projections(store, encryption, "v1", p)
        await recover_projections(store, encryption, "v1", p)
        wire = json.dumps(remote.calls)
        assert "1992" not in wire and "June" not in wire and "birth_place" not in wire
        response = await flow.handle(message("What does my relationship with Alice suggest?"))
        assert "cooperation" in response.text
        generation = [b for path, b in remote.calls if path.endswith("responses")][-1]
        assert generation["knowledge_refs"]
        async with store.transaction() as session:
            linked = LinkedContext(session, encryption, "v1", p)
            interpretations = [
                linked.repo.decode(r)
                for r in await linked.repo.rows(user_id)
                if not r.deleted and linked.repo.decode(r).knowledge_kind == "interpretation"
            ]
            assert interpretations and interpretations[0].sources
            assert (await linked.knowledge.own_birth(user_id)).ref in interpretations[0].sources
        await recover_projections(store, encryption, "v1", p)
        recall = await flow.handle(message("What do you remember about Alice?"))
        assert "Prior interpretation" in recall.text
        removed = await flow.handle(message("forget my girlfriend's birthday"))
        assert "Removed" in removed.text and "queued" in removed.text
        async with store.transaction() as session:
            linked = LinkedContext(session, encryption, "v1", p)
            assert not await linked.retrieve(user_id, "Alice")
            tombstones = [r for r in await linked.repo.rows(user_id) if r.deleted]
            assert tombstones and all(r.encrypted_payload is None for r in tombstones)
        await recover_projections(store, encryption, "v1", p)
        await recover_projections(store, encryption, "v1", p)
        async with store.transaction() as session:
            linked = LinkedContext(session, encryption, "v1", p)
            assert not any(r.pending and r.deleted for r in await linked.repo.rows(user_id))
    finally:
        await p.aclose()


async def test_outage_retries_same_operation_withdrawal_keeps_erasure(
    store, encryption, birth_payload
):
    flow, p, remote, user_id = await prepare(store, encryption, birth_payload)
    try:
        await flow.handle(message("We married May 1st, 2020"))
        remote.fail = True
        await recover_projections(store, encryption, "v1", p)
        async with store.transaction() as session:
            linked = LinkedContext(session, encryption, "v1", p)
            rows = await linked.repo.rows(user_id)
            assert all(row.pending for row in rows)
        remote.fail = False
        async with store.transaction() as session:
            for row in await LinkedContext(session, encryption, "v1", p).repo.rows(user_id):
                row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        await recover_projections(store, encryption, "v1", p)
        removed = await flow.handle(message("forget our wedding"))
        assert "queued" in removed.text
        async with store.transaction() as session:
            await ConsentRepository(session).revoke(user_id, "telegram")
        p.knowledge_enabled = False
        await recover_projections(store, encryption, "v1", p)
        assert any(path.endswith("delete") for path, _ in remote.calls)
        async with store.transaction() as session:
            rows = await LinkedContext(session, encryption, "v1", p).repo.rows(user_id)
            assert not any(r.deleted and r.pending for r in rows)
    finally:
        await p.aclose()


async def test_correction_fences_stale_interpretations_and_replaces_name(
    store, encryption, birth_payload
):
    flow, p, remote, user_id = await prepare(store, encryption, birth_payload)
    try:
        await flow.handle(message("My girlfriend is Alice"))
        await flow.handle(message("Her birthday is June 2nd, 1992"))
        await recover_projections(store, encryption, "v1", p)
        await recover_projections(store, encryption, "v1", p)
        await flow.handle(message("What about Alice and our relationship?"))
        async with store.transaction() as session:
            linked = LinkedContext(session, encryption, "v1", p)
            canonical = await linked.knowledge.list(user_id)
            alice = next(s for s in canonical if isinstance(s.record, EntityRecord))
            changed = EntityRecord(
                **{**alice.record.model_dump(), "revision": 2, "label": "Alicia"}
            )
            await linked.knowledge.save(user_id, changed)
            rows = await linked.repo.rows(user_id)
            assert any(r.deleted for r in rows if r.kind == "reading")
            current = next(r for r in rows if r.id == alice.ref.id)
            assert current.pending and current.revision == 2
            assert linked.repo.decode(current).label == "Alicia"
            assert not await linked.retrieve(user_id, "Alice")
    finally:
        await p.aclose()


async def test_significance_override_and_no_remember_no_projection_write(
    store, encryption, birth_payload
):
    flow, p, remote, user_id = await prepare(store, encryption, birth_payload)
    try:
        await flow.handle(message("We married May 1st, 2020"))
        await flow.handle(message("Our wedding is very important to me"))
        async with store.transaction() as session:
            linked = LinkedContext(session, encryption, "v1", p)
            explicit = [
                linked.repo.decode(r)
                for r in await linked.repo.rows(user_id)
                if not r.deleted and linked.repo.decode(r).salience.basis == "user_stated"
            ]
            assert len(explicit) == 1 and explicit[0].salience.score == 1.0
        await flow.handle(message("Our wedding is not important to me now"))
        async with store.transaction() as session:
            linked = LinkedContext(session, encryption, "v1", p)
            explicit = [
                linked.repo.decode(r)
                for r in await linked.repo.rows(user_id)
                if not r.deleted and linked.repo.decode(r).salience.basis == "user_stated"
            ]
            assert len(explicit) == 1 and explicit[0].salience.score == 0.1
            before = len(await linked.repo.rows(user_id))
        await flow.handle(message("Don't remember this. Our wedding is very important to me"))
        async with store.transaction() as session:
            assert (
                len(await LinkedContext(session, encryption, "v1", p).repo.rows(user_id)) == before
            )
    finally:
        await p.aclose()


async def test_wrong_owner_stale_or_changed_payload_is_not_used(store, encryption, birth_payload):
    flow, p, remote, user_id = await prepare(store, encryption, birth_payload)
    try:
        await flow.handle(message("We married May 1st, 2020"))
        await recover_projections(store, encryption, "v1", p)
        # A correctly scoped response with untrusted/altered text still has to
        # equal this owner's encrypted desired payload and current source revision.
        for r in remote.records.values():
            r["projection"]["summary"] = "Foreign or injected summary"
        async with store.transaction() as session:
            assert not await LinkedContext(session, encryption, "v1", p).retrieve(
                user_id, "wedding"
            )
    finally:
        await p.aclose()


async def test_natal_profile_revision_invalidates_event_interpretation(
    store, encryption, birth_payload
):
    flow, p, remote, user_id = await prepare(store, encryption, birth_payload)
    try:
        await flow.handle(message("We married May 1st, 2020"))
        await recover_projections(store, encryption, "v1", p)
        await flow.handle(message("Reflect on our wedding"))
        async with store.transaction() as session:
            linked = LinkedContext(session, encryption, "v1", p)
            readings = [row for row in await linked.repo.rows(user_id) if row.kind == "reading"]
            assert readings and not any(row.deleted for row in readings)
            old_birth = await linked.knowledge.own_birth(user_id)
            assert old_birth.ref in linked.repo.decode(readings[0]).sources
            assert await linked.references(user_id, "my birthday") == (old_birth.ref,)
            assert await linked.references(user_id, "My birthday means a lot to me") == (
                old_birth.ref,
            )
            await BirthProfileRepository(session, encryption, policy_version="v1").save(
                user_id, birth_payload
            )
            new_birth = await linked.knowledge.own_birth(user_id)
            assert new_birth.ref.revision == old_birth.ref.revision + 1
            rows = await linked.repo.rows(user_id)
            assert all(
                row.deleted and row.pending and row.encrypted_payload is None
                for row in rows
                if row.kind == "reading"
            )
            assert not await linked.retrieve(user_id, "wedding")
    finally:
        await p.aclose()
