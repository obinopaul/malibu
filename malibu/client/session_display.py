"""Session display — renders ACP session_update notifications to the terminal.

Handles all 11 session update types:
  UserMessageChunk, AgentMessageChunk, AgentThoughtChunk,
  ToolCallStart, ToolCallProgress, AgentPlanUpdate,
  AvailableCommandsUpdate, CurrentModeUpdate, ConfigOptionUpdate,
  SessionInfoUpdate, UsageUpdate
"""

from __future__ import annotations

import sys
from typing import Any

from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AudioContentBlock,
    AvailableCommandsUpdate,
    ConfigOptionUpdate,
    CurrentModeUpdate,
    EmbeddedResourceContentBlock,
    ImageContentBlock,
    ResourceContentBlock,
    SessionInfoUpdate,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UsageUpdate,
    UserMessageChunk,
)


def display_session_update(session_id: str, update: Any, **kwargs: Any) -> None:
    """Render a session update to the console."""
    handler = _HANDLERS.get(type(update))
    if handler:
        handler(session_id, update)
    else:
        _print_generic(session_id, update)


def _print_agent_message(session_id: str, update: AgentMessageChunk) -> None:
    content = update.content
    if isinstance(content, TextContentBlock):
        text = content.text
    elif isinstance(content, ImageContentBlock):
        text = "[image]"
    elif isinstance(content, AudioContentBlock):
        text = "[audio]"
    elif isinstance(content, ResourceContentBlock):
        text = f"[resource: {content.uri or content.name}]"
    elif isinstance(content, EmbeddedResourceContentBlock):
        text = "[embedded resource]"
    else:
        text = str(content)
    sys.stdout.write(text)
    sys.stdout.flush()


def _print_thought(session_id: str, update: AgentThoughtChunk) -> None:
    content = update.content
    if isinstance(content, TextContentBlock):
        print(f"\033[90m(thinking: {content.text})\033[0m", end="", flush=True)


def _print_tool_call_start(session_id: str, update: ToolCallStart) -> None:
    kind = update.kind or "tool"
    status = update.status or "pending"
    print(f"\n\033[36m[{kind}] {update.title} ({status})\033[0m", flush=True)


def _print_tool_call_progress(session_id: str, update: ToolCallProgress) -> None:
    status = update.status or ""
    if update.content:
        for item in update.content:
            if hasattr(item, "content") and hasattr(item.content, "text"):
                print(f"  {item.content.text}", flush=True)
    if status in ("completed", "failed"):
        icon = "\033[32m✓\033[0m" if status == "completed" else "\033[31m✗\033[0m"
        print(f"  {icon} {update.title or 'Tool call'} {status}", flush=True)


def _print_plan(session_id: str, update: AgentPlanUpdate) -> None:
    if not update.entries:
        return
    print("\n\033[33m── Plan ──\033[0m")
    for i, entry in enumerate(update.entries, 1):
        marker = {
            "completed": "\033[32m✓\033[0m",
            "in_progress": "\033[33m▶\033[0m",
            "pending": "\033[90m○\033[0m",
        }.get(entry.status, "○")
        print(f"  {marker} {i}. {entry.content}")
    print()


def _print_available_commands(session_id: str, update: AvailableCommandsUpdate) -> None:
    if update.available_commands:
        cmds = ", ".join(c.command for c in update.available_commands)
        print(f"\033[90m[Available commands: {cmds}]\033[0m", flush=True)


def _print_current_mode(session_id: str, update: CurrentModeUpdate) -> None:
    print(f"\033[90m[Mode changed to: {update.current_mode_id}]\033[0m", flush=True)


def _print_config_option(session_id: str, update: ConfigOptionUpdate) -> None:
    for opt in update.config_options:
        inner = opt.root
        print(f"\033[90m[Config: {inner.id} = {inner.current_value}]\033[0m", flush=True)


def _print_session_info(session_id: str, update: SessionInfoUpdate) -> None:
    title = getattr(update, "title", None)
    if title:
        print(f"\033[90m[Session: {title}]\033[0m", flush=True)


def _print_usage(session_id: str, update: UsageUpdate) -> None:
    input_tokens = getattr(update, "input_tokens", None)
    output_tokens = getattr(update, "output_tokens", None)
    if input_tokens is not None or output_tokens is not None:
        print(f"\033[90m[Usage: in={input_tokens}, out={output_tokens}]\033[0m", flush=True)


def _print_user_message(session_id: str, update: UserMessageChunk) -> None:
    content = update.content
    if isinstance(content, TextContentBlock):
        print(f"\033[94mYou: {content.text}\033[0m", end="", flush=True)


def _print_generic(session_id: str, update: Any) -> None:
    print(f"\033[90m[Update: {type(update).__name__}]\033[0m", flush=True)


_HANDLERS: dict[type, Any] = {
    AgentMessageChunk: _print_agent_message,
    AgentThoughtChunk: _print_thought,
    ToolCallStart: _print_tool_call_start,
    ToolCallProgress: _print_tool_call_progress,
    AgentPlanUpdate: _print_plan,
    AvailableCommandsUpdate: _print_available_commands,
    CurrentModeUpdate: _print_current_mode,
    ConfigOptionUpdate: _print_config_option,
    SessionInfoUpdate: _print_session_info,
    UsageUpdate: _print_usage,
    UserMessageChunk: _print_user_message,
}
