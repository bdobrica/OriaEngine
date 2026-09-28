"""Stateless private-network MCP service. No identity, database or model calls."""

import logging

import uvicorn
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams
from starlette.requests import Request
from starlette.responses import JSONResponse

from oria_engine.astrology.contracts import NatalRequest, NatalResult
from oria_engine.astrology.transits import TransitRequest, TransitResult
from oria_engine.observability import JsonFormatter

from .engine import calculate, calculate_transits, metadata


class PrivateErrors(Middleware):
    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        try:
            return await call_next(context)
        except Exception:
            raise ToolError("Invalid calculation request or calculation unavailable") from None


def create_server() -> FastMCP:
    server = FastMCP(
        "Oria Astrology",
        version="1",
        mask_error_details=True,
        strict_input_validation=True,
        middleware=[PrivateErrors()],
    )

    @server.tool(
        name="calculate_natal_chart",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def calculate_natal_chart(request: NatalRequest) -> NatalResult:
        """Calculate a tropical natal chart; unknown time returns explicit unavailability."""
        return calculate(request)

    @server.tool(
        name="calculate_transits",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def transits(request: TransitRequest) -> TransitResult:
        """Calculate positions and aspects to fixed natal longitudes at an explicit UTC target."""
        return calculate_transits(request)

    @server.custom_route("/healthz", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @server.custom_route("/readyz", methods=["GET"])
    async def ready(request: Request) -> JSONResponse:
        try:
            metadata()
            calculate(
                NatalRequest.model_validate(
                    dict(
                        timestamp_utc="2000-01-01T12:00:00Z",
                        birth_time_accuracy="exact",
                        latitude=0,
                        longitude=0,
                    )
                )
            )
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return server


def configure_service_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # FastMCP's Rich handlers must not bypass the payload-free formatter.
    for name in logging.root.manager.loggerDict:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


def main() -> None:
    configure_service_logging()
    server = create_server()
    uvicorn.run(
        server.http_app(path="/mcp", stateless_http=True, json_response=True),
        host="0.0.0.0",
        port=8000,
        log_config=None,
        access_log=False,
    )
