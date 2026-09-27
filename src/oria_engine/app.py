"""HTTP gateway skeleton; integrations register readiness checks and lifecycle resources."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from time import perf_counter
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from oria_engine.config import Settings, load_settings
from oria_engine.observability import configure_logging, correlation_scope

logger = logging.getLogger(__name__)
ReadinessCheck = Callable[[], Awaitable[bool]]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, bool]


class CorrelationMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with correlation_scope() as identifier:
            started = perf_counter()
            status = 500
            response_started = False

            async def send_response(message: Message) -> None:
                nonlocal status, response_started
                if message["type"] == "http.response.start":
                    response_started = True
                    status = message["status"]
                    message["headers"] = [
                        *message.get("headers", []),
                        (b"x-request-id", identifier.encode("ascii")),
                    ]
                await send(message)

            try:
                await self.app(scope, receive, send_response)
            except Exception:
                logger.error("request_failed")
                if response_started:
                    raise
                await JSONResponse({"detail": "Internal Server Error"}, status_code=500)(
                    scope, receive, send_response
                )
            finally:
                logger.info(
                    "request_completed",
                    extra={
                        "status_code": status,
                        "duration_ms": round((perf_counter() - started) * 1000, 3),
                    },
                )


def create_app(
    settings: Settings | None = None,
    *,
    readiness_checks: Mapping[str, ReadinessCheck] | None = None,
) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    configure_logging(settings)
    checks = dict(readiness_checks or {})

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.started = False
        async with AsyncExitStack() as resources:
            # Future adapters enter their async contexts here for reverse-order cleanup.
            app.state.resources = resources
            app.state.started = True
            logger.info("application_started")
            try:
                yield
            finally:
                app.state.started = False
        logger.info("application_stopped")

    app = FastAPI(
        title="OriaEngine",
        lifespan=lifespan,
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.app_env == "production" else "/openapi.json",
    )
    app.state.started = False
    app.add_middleware(CorrelationMiddleware)

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse()

    @app.get(
        "/readyz", response_model=ReadinessResponse, responses={503: {"model": ReadinessResponse}}
    )
    async def readyz() -> JSONResponse:
        async def check(checker: ReadinessCheck) -> bool:
            try:
                async with asyncio.timeout(2):
                    return await checker() is True
            except Exception:
                return False

        results = dict(
            zip(checks, await asyncio.gather(*(check(c) for c in checks.values())), strict=True)
        )
        ready = app.state.started and all(results.values())
        response = ReadinessResponse(status="ready" if ready else "not_ready", checks=results)
        return JSONResponse(response.model_dump(), status_code=200 if ready else 503)

    return app
