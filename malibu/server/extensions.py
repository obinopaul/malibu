"""ACP extension method / notification handlers.

Provides the ext_method and ext_notification dispatchers for custom
protocol extensions.
"""

from __future__ import annotations

from typing import Any

from acp.exceptions import RequestError
from malibu.telemetry.logging import get_logger

log = get_logger(__name__)


class ExtensionRegistry:
    """Registry for custom ACP extension methods and notifications."""

    def __init__(self) -> None:
        self._methods: dict[str, Any] = {}
        self._notifications: dict[str, Any] = {}

    def register_method(self, method: str, handler: Any) -> None:
        """Register a custom method handler."""
        self._methods[method] = handler

    def register_notification(self, method: str, handler: Any) -> None:
        """Register a custom notification handler."""
        self._notifications[method] = handler

    async def handle_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a custom method call."""
        handler = self._methods.get(method)
        if handler is None:
            raise RequestError.method_not_found(method)
        log.info("ext_method_called", method=method)
        return await handler(params)

    async def handle_notification(self, method: str, params: dict[str, Any]) -> None:
        """Dispatch a custom notification."""
        handler = self._notifications.get(method)
        if handler is None:
            log.warning("ext_notification_unhandled", method=method)
            return
        log.info("ext_notification_called", method=method)
        await handler(params)
