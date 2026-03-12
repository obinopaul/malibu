"""WebSocket route — scaffold for real-time streaming.

Provides a WebSocket endpoint for streaming ACP session updates
to browser-based or other WebSocket clients.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from malibu.telemetry.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["ws"])


@router.websocket("/session/{session_id}")
async def session_ws(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for streaming session updates.

    Protocol (to be fully wired):
    - Client sends JSON messages with ``{"type": "prompt", "message": "..."}``
    - Server sends JSON session updates as they arrive from the agent.
    """
    await websocket.accept()
    log.info("ws_connected", session_id=session_id)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "prompt":
                # Stub: will be wired to agent.prompt() with streaming
                await websocket.send_json({
                    "type": "error",
                    "message": "WebSocket agent integration not yet wired",
                })
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })
    except WebSocketDisconnect:
        log.info("ws_disconnected", session_id=session_id)
