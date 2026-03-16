"""Authentication providers — API key and JWT strategies."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from abc import ABC, abstractmethod

import bcrypt

from malibu.auth.jwt_handler import JWTHandler
from malibu.config import Settings


class AuthProvider(ABC):
    """Base class for authentication strategies."""

    @abstractmethod
    def authenticate(self, credential: str) -> str | None:
        """Return user_id on success, None on failure."""
        ...


class JWTProvider(AuthProvider):
    """Authenticate via a bearer JWT token."""

    def __init__(self, settings: Settings) -> None:
        self._handler = JWTHandler(settings)

    def authenticate(self, credential: str) -> str | None:
        try:
            claims = self._handler.verify_token(credential)
            return claims.get("sub")
        except Exception:
            return None

    def issue(self, user_id: str) -> str:
        return self._handler.create_token(user_id)


class APIKeyProvider(AuthProvider):
    """Authenticate via a pre-shared hashed API key.

    Keys are stored as bcrypt hashes in the database.  This provider
    accepts a mapping of ``{user_id: bcrypt_hash}`` loaded at startup.
    """

    def __init__(self, key_index: dict[str, str] | None = None) -> None:
        self._key_index: dict[str, str] = key_index or {}

    def authenticate(self, credential: str) -> str | None:
        for user_id, stored_hash in self._key_index.items():
            if bcrypt.checkpw(credential.encode(), stored_hash.encode()):
                return user_id
        return None

    @staticmethod
    def generate_key() -> tuple[str, str]:
        """Generate a fresh API key and its bcrypt hash.

        Returns:
            (plain_key, bcrypt_hash)
        """
        plain_key = secrets.token_urlsafe(32)
        hashed = bcrypt.hashpw(plain_key.encode(), bcrypt.gensalt()).decode()
        return plain_key, hashed

    @staticmethod
    def hash_key(plain_key: str) -> str:
        """Hash an existing API key for storage."""
        return bcrypt.hashpw(plain_key.encode(), bcrypt.gensalt()).decode()


class CompositeAuthProvider(AuthProvider):
    """Try multiple providers in order, return first successful match."""

    def __init__(self, *providers: AuthProvider) -> None:
        self._providers = providers

    def authenticate(self, credential: str) -> str | None:
        for provider in self._providers:
            result = provider.authenticate(credential)
            if result is not None:
                return result
        return None
