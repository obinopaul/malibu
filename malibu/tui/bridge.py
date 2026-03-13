"""Bridge ACP callbacks and custom extension calls into Textual messages."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from textual.message import Message

from acp.schema import PermissionOption, RequestPermissionResponse, ToolCallUpdate

if TYPE_CHECKING:
    from malibu.tui.app import MalibuApp


class SessionUpdateMessage(Message):
    """ACP session update posted into the Textual app."""

    def __init__(self, session_id: str, update: Any) -> None:
        super().__init__()
        self.session_id = session_id
        self.update = update


class PermissionRequestMessage(Message):
    """ACP permission request posted into the Textual app."""

    def __init__(
        self,
        options: list[PermissionOption],
        tool_call: ToolCallUpdate,
        future: asyncio.Future[RequestPermissionResponse],
    ) -> None:
        super().__init__()
        self.options = options
        self.tool_call = tool_call
        self.future = future


class ExtensionRequestMessage(Message):
    """Custom extension method request posted into the Textual app."""

    def __init__(
        self,
        method: str,
        params: dict[str, Any],
        future: asyncio.Future[dict[str, Any]],
    ) -> None:
        super().__init__()
        self.method = method
        self.params = params
        self.future = future


class ExtensionNotificationMessage(Message):
    """Custom extension notification posted into the Textual app."""

    def __init__(self, method: str, params: dict[str, Any]) -> None:
        super().__init__()
        self.method = method
        self.params = params


class TUIBridge:
    """Adapter from MalibuClient callbacks to Textual messages."""

    def __init__(self, app: "MalibuApp") -> None:
        self.app = app

    async def display_handler(self, session_id: str, update: Any, **_: Any) -> None:
        self.app.post_message(SessionUpdateMessage(session_id, update))

    async def permission_handler(
        self,
        options: list[PermissionOption],
        tool_call: ToolCallUpdate,
    ) -> RequestPermissionResponse:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[RequestPermissionResponse] = loop.create_future()
        self.app.post_message(PermissionRequestMessage(options, tool_call, future))
        return await future

    async def extension_method_handler(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.app.post_message(ExtensionRequestMessage(method, params, future))
        return await future

    async def extension_notification_handler(self, method: str, params: dict[str, Any]) -> None:
        self.app.post_message(ExtensionNotificationMessage(method, params))
