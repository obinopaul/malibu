"""FastAPI application factory.

Creates the ASGI app with middleware, lifecycle hooks, and routed endpoints.
This is a scaffold — handlers delegate to the ACP server and client layers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from malibu.config import get_settings
from malibu.telemetry.logging import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info("api_startup", host=settings.api_host, port=settings.api_port)
    yield
    log.info("api_shutdown")


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    from malibu.api.routes import router as api_router
    from malibu.api.websocket import router as ws_router

    settings = get_settings()

    app = FastAPI(
        title="Malibu ACP API",
        version="0.1.0",
        description="HTTP/WebSocket gateway to the Malibu ACP agent.",
        lifespan=_lifespan,
    )

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(ws_router, prefix="/ws")

    return app
