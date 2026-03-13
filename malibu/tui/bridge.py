"""TUI Bridge — adapts MalibuClient callbacks to Textual message posting.

Routes ACP session updates and permission requests from the client layer
into the TUI application via ``app.post_message()``, keeping the transport
and presentation layers cleanly separated.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from textual.message import Message

from acp.schema import (
    PermissionOption,
    RequestPermissionResponse,
    ToolCallUpdate,
)

from malibu.telemetry.logging import get_logger

if TYPE_CHECKING:
    from malibu.tui.app import MalibuApp

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Textual Messages
# ---------------------------------------------------------------------------


class SessionUpdateMessage(Message):
    """Carries an ACP session update into the Textual message loop."""

    def __init__(self, session_id: str, update: Any) -> None:
        super().__init__()
        self.session_id = session_id
        self.update = update


class PermissionRequestMessage(Message):
    """Carries a permission request into the Textual message loop.

    The ``future`` is resolved by the UI once the user makes a choice,
    unblocking the ``permission_handler`` coroutine on the client side.
    """

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


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class TUIBridge:
    """Thin adapter that forwards ACP callbacks to :class:`MalibuApp`.

    Instantiated with a reference to the running Textual application and
    wired into :class:`MalibuClient` as the display/permission handlers.

    Parameters
    ----------
    app:
        The live ``MalibuApp`` instance that will receive messages.
    """

    def __init__(self, app: MalibuApp) -> None:
        self.app = app

    # -- session_update callback -------------------------------------------

    async def display_handler(
        self,
        session_id: str,
        update: Any,
        **kwargs: Any,
    ) -> None:
        """Route an ACP session update to the TUI via message posting.

        This method has the same signature as
        ``display_session_update(session_id, update, **kwargs)`` so it can
        be used as a drop-in replacement inside ``MalibuClient``.
        """
        log.debug(
            "bridge_session_update",
            session_id=session_id,
            update_type=type(update).__name__,
        )
        self.app.post_message(SessionUpdateMessage(session_id, update))

    # -- request_permission callback ---------------------------------------

    async def permission_handler(
        self,
        options: list[PermissionOption],
        tool_call: ToolCallUpdate,
    ) -> RequestPermissionResponse:
        """Open the approval modal and wait for the user's decision.

        Creates an :class:`asyncio.Future` that the TUI resolves once the
        user interacts with the :class:`ApprovalModal`.  The future's result
        is a :class:`RequestPermissionResponse`.
        """
        log.debug(
            "bridge_permission_request",
            title=tool_call.title,
            option_count=len(options),
        )
        loop = asyncio.get_event_loop()
        future: asyncio.Future[RequestPermissionResponse] = loop.create_future()
        self.app.post_message(
            PermissionRequestMessage(options, tool_call, future)
        )
        return await future
