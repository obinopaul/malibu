"""JWT creation, verification, and refresh utilities.

Uses PyJWT with HS256 by default.  Secrets and algorithm are sourced from Settings.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from malibu.config import Settings


class JWTHandler:
    """Stateless JWT helper bound to application Settings."""

    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret
        self._algorithm = settings.jwt_algorithm
        self._expiry_hours = settings.jwt_expiry_hours

    def create_token(self, user_id: str, *, extra_claims: dict[str, Any] | None = None) -> str:
        """Issue a JWT with standard claims."""
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "sub": user_id,
            "iat": now,
            "exp": now + timedelta(hours=self._expiry_hours),
        }
        if extra_claims:
            payload.update(extra_claims)
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def verify_token(self, token: str) -> dict[str, Any]:
        """Decode and verify a JWT.  Raises ``jwt.InvalidTokenError`` on failure."""
        return jwt.decode(token, self._secret, algorithms=[self._algorithm])

    def refresh_token(self, token: str) -> str:
        """Verify an existing token and issue a fresh one with the same claims."""
        claims = self.verify_token(token)
        user_id: str = claims["sub"]
        extra = {k: v for k, v in claims.items() if k not in ("sub", "iat", "exp")}
        return self.create_token(user_id, extra_claims=extra or None)
