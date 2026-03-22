"""Queued processor for ACP updates and custom TUI events."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AvailableCommandsUpdate,
    ConfigOptionUpdate,
    CurrentModeUpdate,
    SessionInfoUpdate,
    ToolCallProgress,
    ToolCallStart,
    UsageUpdate,
    UserMessageChunk,
)

from malibu.tui.protocol import extract_event_type, extract_payload

if TYPE_CHECKING:
    from malibu.tui.screens.chat import ChatScreen


class UpdateProcessor:
    """Serialise all UI updates through one queue."""

    def __init__(self, screen: "ChatScreen") -> None:
        self.screen = screen
        self._pending: deque[tuple[str, Any, bool]] = deque()
        self._draining = False

    def enqueue_session_update(self, update: Any, *, from_history: bool = False) -> None:
        self._pending.append(("session_update", update, from_history))
        self._drain()

    def enqueue_tui_event(self, params: dict[str, Any], *, from_history: bool = False) -> None:
        self._pending.append(("tui_event", params, from_history))
        self._drain()

    def _drain(self) -> None:
        if self._draining:
            return
        self._draining = True
        try:
            while self._pending:
                kind, payload, from_history = self._pending.popleft()
                if kind == "session_update":
                    self.apply_session_update(payload, from_history=from_history)
                else:
                    self.apply_tui_event(payload, from_history=from_history)
        finally:
            self._draining = False

    def apply_session_update(self, update: Any, *, from_history: bool = False) -> None:
        screen = self.screen
        if isinstance(update, UserMessageChunk):
            screen.on_user_message_chunk(update, from_history=from_history)
        elif isinstance(update, AgentMessageChunk):
            screen.on_agent_message_chunk(update, from_history=from_history)
        elif isinstance(update, AgentThoughtChunk):
            screen.on_thought_chunk(update)
        elif isinstance(update, ToolCallStart):
            screen.on_tool_call_start(update)
        elif isinstance(update, ToolCallProgress):
            screen.on_tool_call_progress(update)
        elif isinstance(update, AgentPlanUpdate):
            screen.on_plan_update(update)
        elif isinstance(update, CurrentModeUpdate):
            screen.on_mode_update(update)
        elif isinstance(update, SessionInfoUpdate):
            screen.on_session_info_update(update)
        elif isinstance(update, ConfigOptionUpdate):
            screen.on_config_option_update(update)
        elif isinstance(update, AvailableCommandsUpdate):
            screen.on_available_commands_update(update)
        elif isinstance(update, UsageUpdate):
            screen.on_usage_update(update)

    def apply_tui_event(self, params: dict[str, Any], *, from_history: bool = False) -> None:
        screen = self.screen
        event_type = extract_event_type(params)
        payload = extract_payload(params)
        if event_type == "tool_group":
            screen.on_tool_group_event(payload, from_history=from_history)
        elif event_type == "status":
            screen.on_status_event(payload)
        elif event_type == "notification":
            screen.on_notification_event(payload)
        elif event_type == "session_metadata":
            screen.on_session_metadata_event(payload)
