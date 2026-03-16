"""Tests for malibu.auth module."""

from __future__ import annotations

import jwt as pyjwt
import pytest

from malibu.auth.jwt_handler import JWTHandler
from malibu.auth.providers import APIKeyProvider, CompositeAuthProvider, JWTProvider
from malibu.config import Settings


def _make_settings(**overrides) -> Settings:
    defaults = dict(
        database_url="sqlite+aiosqlite:///test.db",
        jwt_secret="test-secret-key-for-auth-tests",
        jwt_algorithm="HS256",
        jwt_expiry_hours=1,
        llm_api_key="sk-test",
    )
    defaults.update(overrides)
    return Settings(**defaults)


class TestJWTHandler:
    def test_create_and_verify_token(self):
        handler = JWTHandler(_make_settings())
        token = handler.create_token("user-1", extra_claims={"role": "admin"})
        assert isinstance(token, str)

        payload = handler.verify_token(token)
        assert payload["sub"] == "user-1"
        assert payload["role"] == "admin"

    def test_invalid_token_raises(self):
        handler = JWTHandler(_make_settings())
        with pytest.raises(pyjwt.InvalidTokenError):
            handler.verify_token("not-a-valid-token")

    def test_refresh_token(self):
        handler = JWTHandler(_make_settings())
        token = handler.create_token("user-1")
        refreshed = handler.refresh_token(token)
        # Both tokens should decode to the same user
        orig_claims = handler.verify_token(token)
        new_claims = handler.verify_token(refreshed)
        assert orig_claims["sub"] == new_claims["sub"] == "user-1"


class TestAPIKeyProvider:
    def test_generate_key(self):
        key, hashed = APIKeyProvider.generate_key()
        assert isinstance(key, str)
        assert len(key) > 20
        assert isinstance(hashed, str)

    def test_authenticate_key(self):
        key, hashed = APIKeyProvider.generate_key()
        provider = APIKeyProvider(key_index={"user-1": hashed})
        result = provider.authenticate(key)
        assert result == "user-1"

    def test_invalid_key_returns_none(self):
        _, hashed = APIKeyProvider.generate_key()
        provider = APIKeyProvider(key_index={"user-1": hashed})
        result = provider.authenticate("wrong-key-value")
        assert result is None

    def test_hash_key(self):
        hashed = APIKeyProvider.hash_key("my-test-key")
        assert isinstance(hashed, str)
        assert hashed.startswith("$2")  # bcrypt prefix


class TestCompositeAuthProvider:
    def test_composite_delegates_to_jwt(self):
        settings = _make_settings()
        jwt_provider = JWTProvider(settings)
        composite = CompositeAuthProvider(jwt_provider)
        handler = JWTHandler(settings)
        token = handler.create_token("user-1")
        result = composite.authenticate(token)
        assert result == "user-1"

    def test_composite_falls_through(self):
        settings = _make_settings()
        jwt_provider = JWTProvider(settings)
        api_provider = APIKeyProvider(key_index={})
        composite = CompositeAuthProvider(jwt_provider, api_provider)
        result = composite.authenticate("not-a-valid-anything")
        assert result is None
