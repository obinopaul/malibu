"""Auth middleware for wrapping ACP handlers with authentication."""

from __future__ import annotations

from typing import Any, Callable

from malibu.auth.providers import AuthProvider


class AuthMiddleware:
    """Extracts credentials from ACP metadata and verifies them.

    Usage:
        middleware = AuthMiddleware(composite_provider)
        user_id = middleware.verify(metadata_dict)
    """

    HEADER_KEY = "authorization"

    def __init__(self, provider: AuthProvider) -> None:
        self._provider = provider

    def verify(self, metadata: dict[str, Any] | None) -> str | None:
        """Extract the bearer/api-key credential from metadata and authenticate.

        Returns the user_id on success, None on failure.
        """
        if not metadata:
            return None

        auth_value = metadata.get(self.HEADER_KEY, "")
        if not auth_value:
            return None

        # Strip "Bearer " prefix if present
        if auth_value.lower().startswith("bearer "):
            credential = auth_value[7:]
        else:
            credential = auth_value

        return self._provider.authenticate(credential)

    def require(self, metadata: dict[str, Any] | None) -> str:
        """Like verify() but raises ValueError when auth fails."""
        user_id = self.verify(metadata)
        if user_id is None:
            raise ValueError("Authentication required")
        return user_id
