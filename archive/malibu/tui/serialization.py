"""Serialization helpers for ACP session updates in bootstrap payloads."""

from __future__ import annotations

from typing import Any

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

_UPDATE_TYPES = {
    "agent_message_chunk": AgentMessageChunk,
    "plan": AgentPlanUpdate,
    "agent_thought_chunk": AgentThoughtChunk,
    "available_commands_update": AvailableCommandsUpdate,
    "config_option_update": ConfigOptionUpdate,
    "current_mode_update": CurrentModeUpdate,
    "session_info_update": SessionInfoUpdate,
    "tool_call_update": ToolCallProgress,
    "tool_call": ToolCallStart,
    "usage_update": UsageUpdate,
    "user_message_chunk": UserMessageChunk,
}


def deserialize_session_update(data: dict[str, Any]) -> Any:
    """Create an ACP model from a serialized session update dictionary."""
    update_type = data.get("sessionUpdate") or data.get("session_update")
    model = _UPDATE_TYPES.get(str(update_type))
    if model is None:
        return data
    return model.model_validate(data)
