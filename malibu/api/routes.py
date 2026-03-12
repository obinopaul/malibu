"""REST API routes — scaffold for HTTP endpoints.

These routes expose the ACP agent's capabilities over HTTP for
clients that cannot use stdio (e.g. web UIs, mobile apps).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["acp"])


# ── Request / Response models ─────────────────────────────────

class SessionCreateRequest(BaseModel):
    cwd: str = "."


class SessionCreateResponse(BaseModel):
    session_id: str


class PromptRequest(BaseModel):
    session_id: str
    message: str


class PromptResponse(BaseModel):
    stop_reason: str | None = None


class ModeChangeRequest(BaseModel):
    session_id: str
    mode_id: str


class ConfigOptionRequest(BaseModel):
    session_id: str
    config_id: str
    value: Any


# ── Endpoints (stubs — to be wired to MalibuAgent) ───────────

@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/sessions", response_model=SessionCreateResponse)
async def create_session(req: SessionCreateRequest) -> SessionCreateResponse:
    raise HTTPException(501, "Not yet wired to agent backend")


@router.post("/prompt", response_model=PromptResponse)
async def prompt(req: PromptRequest) -> PromptResponse:
    raise HTTPException(501, "Not yet wired to agent backend")


@router.post("/sessions/mode")
async def set_mode(req: ModeChangeRequest) -> dict[str, str]:
    raise HTTPException(501, "Not yet wired to agent backend")


@router.post("/sessions/config")
async def set_config(req: ConfigOptionRequest) -> dict[str, str]:
    raise HTTPException(501, "Not yet wired to agent backend")


@router.get("/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    raise HTTPException(501, "Not yet wired to agent backend")
