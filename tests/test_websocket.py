"""Tests for malibu.api.websocket — WebSocket endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from malibu.api.app import create_app


@pytest.fixture
def api_client():
    return TestClient(create_app())


class TestWebSocketEndpoint:
    def test_ping_pong(self, api_client):
        with api_client.websocket_connect("/ws/session/test-sess") as ws:
            ws.send_json({"type": "ping"})
            resp = ws.receive_json()
            assert resp["type"] == "pong"

    def test_unknown_message_type(self, api_client):
        with api_client.websocket_connect("/ws/session/test-sess") as ws:
            ws.send_json({"type": "bogus"})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "Unknown message type" in resp["message"]

    def test_prompt_returns_not_wired(self, api_client):
        with api_client.websocket_connect("/ws/session/test-sess") as ws:
            ws.send_json({"type": "prompt", "message": "hello"})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "not yet wired" in resp["message"].lower()
