import asyncio
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from oria_engine.app import create_app
from oria_engine.observability import correlation_id


def test_health_readiness_and_shutdown():
    app = create_app()
    closed = []
    with TestClient(app) as client:
        app.state.resources.callback(closed.append, True)
        response = client.get("/healthz", headers={"X-Request-ID": "untrusted-user-data"})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert UUID(response.headers["x-request-id"]).version == 4
        assert client.get("/readyz").json() == {"status": "ready", "checks": {}}
    assert not app.state.started
    assert closed == [True]
    assert correlation_id.get() is None


async def test_not_ready_without_lifespan():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        assert (await client.get("/readyz")).status_code == 503


@pytest.mark.parametrize("failure", ["false", "exception", "timeout"])
def test_failed_dependency_does_not_affect_liveness(failure):
    async def dependency():
        if failure == "exception":
            raise RuntimeError("private dependency details")
        if failure == "timeout":
            await asyncio.sleep(10)
        return False

    with TestClient(create_app(readiness_checks={"storage": dependency})) as client:
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready", "checks": {"storage": False}}
        assert client.get("/healthz").status_code == 200


def test_successful_dependency():
    async def dependency():
        return True

    with TestClient(create_app(readiness_checks={"storage": dependency})) as client:
        assert client.get("/readyz").json() == {"status": "ready", "checks": {"storage": True}}


def test_failed_request_has_safe_response_and_correlation():
    app = create_app()

    @app.get("/failure")
    async def failure():
        raise RuntimeError("private failure detail")

    with TestClient(app) as client:
        response = client.get("/failure")
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal Server Error"}
        assert UUID(response.headers["x-request-id"]).version == 4
    assert correlation_id.get() is None


async def test_concurrent_request_ids_are_independent():
    app = create_app()

    @app.get("/context")
    async def context():
        identifier = correlation_id.get()
        await asyncio.sleep(0)
        assert correlation_id.get() == identifier
        return {"id": identifier}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = await asyncio.gather(*(client.get("/context") for _ in range(10)))
    identifiers = {response.headers["x-request-id"] for response in responses}
    assert len(identifiers) == 10
    assert all(response.json()["id"] == response.headers["x-request-id"] for response in responses)
    assert correlation_id.get() is None
