"""ChatScreen — primary conversation screen for the Malibu TUI.

Layout
------
::

    ┌─────────────────────────────────────────────────┐
    │  StatusBar (mode, tokens, session info)          │
    ├──────────────────────────┬──────────────────────┤
    │  MessageList (scrollable)│  PlanPanel (toggle)   │
    │                          │                       │
    ├──────────────────────────┴──────────────────────┤
    │  ChatInput                                       │
    └─────────────────────────────────────────────────┘

Handles:
  - SessionUpdateMessage  → routes to the correct widget
  - PermissionRequestMessage → pushes ApprovalModal, resolves future
  - ChatInput.Submitted   → sends prompt via ``self.app.send_prompt``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Static

from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AvailableCommandsUpdate,
    ConfigOptionUpdate,
    CurrentModeUpdate,
    ImageContentBlock,
    SessionInfoUpdate,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UsageUpdate,
    UserMessageChunk,
)

from malibu.tui.bridge import PermissionRequestMessage, SessionUpdateMessage
from malibu.tui.widgets.chat_input import ChatInput
from malibu.tui.widgets.message_list import MessageList
from malibu.tui.widgets.plan_panel import PlanPanel
from malibu.tui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# ChatScreen
# ---------------------------------------------------------------------------


class ChatScreen(Screen):
    """Primary conversation screen."""

    BINDINGS = [
        Binding("ctrl+p", "toggle_plan", "Toggle Plan", show=True),
        Binding("ctrl+l", "clear_messages", "Clear", show=True),
    ]

    DEFAULT_CSS = """
    ChatScreen {
        layout: vertical;
    }
    #chat-body {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield StatusBar()
        with Horizontal(id="chat-body"):
            yield MessageList()
            yield PlanPanel()
        yield ChatInput()
        yield Footer()

    # -- ACP update routing ------------------------------------------------

    @on(SessionUpdateMessage)
    def handle_session_update(self, message: SessionUpdateMessage) -> None:
        """Route an ACP session update to the appropriate widget."""
        update = message.update
        msg_list = self.query_one(MessageList)
        status_bar = self.query_one(StatusBar)
        plan_panel = self.query_one(PlanPanel)

        if isinstance(update, AgentMessageChunk):
            content = update.content
            if isinstance(content, TextContentBlock):
                msg_list.append_assistant_text(content.text)
            elif isinstance(content, ImageContentBlock):
                msg_list.append_assistant_text("[image]")
            else:
                msg_list.append_assistant_text(str(content))

        elif isinstance(update, AgentThoughtChunk):
            content = update.content
            if isinstance(content, TextContentBlock):
                msg_list.append_thought(content.text)

        elif isinstance(update, ToolCallStart):
            tool_id = update.tool_call_id or "unknown"
            kind = update.kind or "tool"
            status = update.status or "pending"
            msg_list.add_tool_call(tool_id, update.title, kind, status)

        elif isinstance(update, ToolCallProgress):
            tool_id = update.tool_call_id or "unknown"
            msg_list.update_tool_call(tool_id, update)

        elif isinstance(update, AgentPlanUpdate):
            plan_panel.set_plan(update)
            if not plan_panel.visible:
                plan_panel.visible = True

        elif isinstance(update, UsageUpdate):
            input_tokens = getattr(update, "input_tokens", 0) or 0
            output_tokens = getattr(update, "output_tokens", 0) or 0
            status_bar.set_usage(input_tokens, output_tokens)

        elif isinstance(update, CurrentModeUpdate):
            status_bar.set_mode(update.current_mode_id)

        elif isinstance(update, SessionInfoUpdate):
            title = getattr(update, "title", None)
            if title:
                status_bar.set_session_title(title)

        elif isinstance(update, UserMessageChunk):
            content = update.content
            if isinstance(content, TextContentBlock):
                msg_list.append_user_message(content.text)

        elif isinstance(update, AvailableCommandsUpdate):
            if update.available_commands:
                cmds = ", ".join(c.command for c in update.available_commands)
                msg_list.mount(
                    Static(f"[dim]Available commands: {cmds}[/]", classes="info")
                )

        elif isinstance(update, ConfigOptionUpdate):
            for opt in update.config_options:
                inner = opt.root
                msg_list.mount(
                    Static(
                        f"[dim]Config: {inner.id} = {inner.current_value}[/]",
                        classes="info",
                    )
                )

    # -- Permission requests -----------------------------------------------

    @on(PermissionRequestMessage)
    def handle_permission_request(self, message: PermissionRequestMessage) -> None:
        """Push the ApprovalModal and resolve the bridge future with the result."""
        from acp.schema import (
            AllowedOutcome,
            DeniedOutcome,
            RequestPermissionResponse,
        )
        from malibu.tui.widgets.approval_modal import ApprovalModal

        tool_name = message.tool_call.title or "tool"
        tool_input = message.tool_call.raw_input

        async def _push_and_resolve() -> None:
            result = await self.app.push_screen_wait(
                ApprovalModal(tool_name, tool_input)
            )
            if message.future.done():
                return
            # Map ApprovalResult → ACP RequestPermissionResponse
            if result.action in ("approve", "always_allow"):
                # Find the matching option_id from the permission options
                option_id = "approve"
                if result.action == "always_allow":
                    option_id = "approve_always"
                for opt in message.options:
                    if result.action == "always_allow" and "always" in opt.name.lower():
                        option_id = opt.option_id
                        break
                    elif result.action == "approve" and "once" in opt.name.lower():
                        option_id = opt.option_id
                        break
                if not option_id and message.options:
                    option_id = message.options[0].option_id
                message.future.set_result(
                    RequestPermissionResponse(
                        outcome=AllowedOutcome(outcome="selected", option_id=option_id)
                    )
                )
            else:
                message.future.set_result(
                    RequestPermissionResponse(
                        outcome=DeniedOutcome(outcome="cancelled")
                    )
                )

        self.app.call_later(_push_and_resolve)

    # -- Chat input --------------------------------------------------------

    @on(ChatInput.Submitted)
    def handle_chat_submitted(self, message: ChatInput.Submitted) -> None:
        """Forward submitted text to the application's send_prompt method."""
        if hasattr(self.app, "send_prompt"):
            self.app.send_prompt(message.text)  # type: ignore[attr-defined]

    # -- Key bindings ------------------------------------------------------

    def action_toggle_plan(self) -> None:
        self.query_one(PlanPanel).toggle()

    def action_clear_messages(self) -> None:
        self.query_one(MessageList).clear_messages()
