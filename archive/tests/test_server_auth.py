"""Tests for malibu.server.auth — ServerAuthHandler bridge."""

from __future__ import annotations

import pytest

from malibu.config import Settings
from malibu.server.auth import ServerAuthHandler


@pytest.fixture
def settings():
    return Settings(
        database_url="sqlite:///test.db",
        jwt_secret="a-long-enough-secret-key-for-tests-32ch",
        llm_model="openai:gpt-4o-mini",
        allowed_paths=["."],
    )


@pytest.fixture
def handler(settings):
    return ServerAuthHandler(settings)


class TestServerAuthHandler:
    async def test_authenticate_jwt_with_valid_token(self, handler):
        # Issue a token first
        token = handler._jwt_handler.create_token("user-1")
        resp = await handler.authenticate("jwt", token=token)
        assert resp is not None
        assert resp.field_meta is not None
        assert "token" in resp.field_meta

    async def test_authenticate_jwt_with_invalid_token(self, handler):
        resp = await handler.authenticate("jwt", token="bad-token")
        assert resp is None

    async def test_authenticate_unknown_method(self, handler):
        resp = await handler.authenticate("unknown_method")
        assert resp is None

    async def test_authenticate_api_key_no_keys_configured(self, handler):
        resp = await handler.authenticate("api_key", api_key="some-key")
        assert resp is None
