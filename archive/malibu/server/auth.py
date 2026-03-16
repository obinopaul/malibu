"""Authentication bridge for ACP — wraps auth middleware into the ACP authenticate method."""

from __future__ import annotations

from typing import Any

from acp.schema import AuthenticateResponse

from malibu.auth.jwt_handler import JWTHandler
from malibu.auth.providers import APIKeyProvider, CompositeAuthProvider, JWTProvider
from malibu.config import Settings


class ServerAuthHandler:
    """Handles the ACP authenticate() method and token lifecycle."""

    def __init__(self, settings: Settings) -> None:
        self._jwt_handler = JWTHandler(settings)
        self._jwt_provider = JWTProvider(settings)
        self._api_key_provider = APIKeyProvider()
        self._composite = CompositeAuthProvider(self._jwt_provider, self._api_key_provider)

    async def authenticate(self, method_id: str, **kwargs: Any) -> AuthenticateResponse | None:
        """Process an authenticate request.

        Supports:
          - 'jwt': Issue a new JWT for the provided user_id
          - 'api_key': Validate an API key and return a JWT
        """
        if method_id == "jwt":
            # Client already has a JWT, verify and return refresh
            token = kwargs.get("token", "")
            user_id = self._jwt_provider.authenticate(token)
            if user_id:
                new_token = self._jwt_handler.refresh_token(token)
                return AuthenticateResponse(field_meta={"token": new_token})
            return None

        if method_id == "api_key":
            api_key = kwargs.get("api_key", "")
            user_id = self._api_key_provider.authenticate(api_key)
            if user_id:
                token = self._jwt_handler.create_token(user_id)
                return AuthenticateResponse(field_meta={"token": token})
            return None

        return None
