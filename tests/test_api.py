"""Tests for malibu.api routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from malibu.api.app import create_app


@pytest.fixture
def api_client():
    app = create_app()
    return TestClient(app)


def test_health(api_client):
    resp = api_client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_session_stub(api_client):
    resp = api_client.post("/api/v1/sessions", json={"cwd": "."})
    assert resp.status_code == 501


def test_prompt_stub(api_client):
    resp = api_client.post("/api/v1/prompt", json={"session_id": "1", "message": "hi"})
    assert resp.status_code == 501


def test_list_sessions_stub(api_client):
    resp = api_client.get("/api/v1/sessions")
    assert resp.status_code == 501
