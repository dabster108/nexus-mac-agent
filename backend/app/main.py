"""FastAPI application factory.

Initialisation only — no business logic. Everything the app does lives in
:mod:`app.api`, :mod:`app.agent` and below.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers import ALL_ROUTERS
from app.api.websocket import ws_router
from app.core.config import Settings, get_settings
from app.core.errors import ErrorCode, NexusError
from app.core.logging import configure_logging, get_logger
from app.mcp.registry import get_mcp_pool
from app.observations.wiring import build_scheduler

logger = get_logger(__name__)

DESCRIPTION = """
Agent runtime for NEXUS, an AI operating system for macOS.

Mac capabilities are never exposed as endpoints. They are tools behind the MCP
layer, reached only through the agent:

    FastAPI -> LangGraph -> Tool Registry -> MCP -> Mac capabilities
"""

TAGS_METADATA = [
    {"name": "health", "description": "Liveness."},
    {"name": "agent", "description": "Send messages and stream execution events."},
    {"name": "tasks", "description": "Inspect and cancel agent runs."},
    {"name": "tools", "description": "Discover tools. Information only."},
    {"name": "permissions", "description": "Approve or deny CONFIRM tool calls."},
    {"name": "context", "description": "What NEXUS can currently see. Read-only."},
    {"name": "memory", "description": "What NEXUS remembers. Read-only; forgetting goes through approval."},
    {"name": "observations", "description": "What NEXUS noticed on its own. Read-only."},
    {"name": "mcp", "description": "MCP server status."},
    {"name": "models", "description": "Configured model providers."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "NEXUS backend starting on http://%s:%s (default provider: %s)",
            settings.backend_host,
            settings.backend_port,
            settings.default_model_provider,
        )
        # Opened and closed in this one task, as the stdio transport requires.
        # Keeping MCP servers alive across requests is what lets a development
        # server started by one message survive to the next.
        pool = get_mcp_pool()
        await pool.open()

        # Proactive observation. Deliberately started *after* the pool: the
        # detector reads through the same SAFE tools everything else uses, and
        # has nothing to look at until they exist.
        scheduler = build_scheduler(pool)
        scheduler.start()
        try:
            yield
        finally:
            await scheduler.stop()
            await pool.close()
            logger.info("NEXUS backend stopped")

    app = FastAPI(
        title="NEXUS Agent Backend",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
        openapi_tags=TAGS_METADATA,
    )

    # The frontend runs on a different origin in development; nothing else is allowed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(NexusError)
    async def handle_nexus_error(_: Request, exc: NexusError) -> JSONResponse:
        # `detail` stays in the log; the client only sees code + clean message.
        logger.error("%s: %s (%s)", exc.code, exc.message, exc.detail or "no detail")
        return JSONResponse(status_code=exc.http_status, content={"error": exc.to_payload()})

    @app.exception_handler(HTTPException)
    async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
        # Same envelope as NexusError so the frontend parses one error shape.
        code = ErrorCode.VALIDATION_ERROR if exc.status_code < 500 else ErrorCode.INTERNAL_ERROR
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": str(code), "message": str(exc.detail)}},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.info("Rejected an invalid request: %s", exc.errors())
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {
                    "code": str(ErrorCode.VALIDATION_ERROR),
                    "message": "The request body is not valid.",
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        # Nothing about the exception reaches the client — it goes to the log.
        logger.exception("Unhandled error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": str(ErrorCode.INTERNAL_ERROR),
                    "message": "The backend hit an unexpected problem.",
                }
            },
        )

    for router in ALL_ROUTERS:
        app.include_router(router)
    app.include_router(ws_router)
    return app


app = create_app()
