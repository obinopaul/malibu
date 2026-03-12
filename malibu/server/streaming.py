"""Streaming helpers — bridges LangGraph async iterators into ACP session_update calls.

Handles:
  - AgentMessageChunk streaming (token-by-token)
  - Tool call chunk accumulation and start/progress/completion
  - Plan (todo) update forwarding
  - Cancellation checks mid-stream
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from acp import (
    start_edit_tool_call,
    start_tool_call,
    text_block,
    tool_content,
    tool_diff_content,
    update_agent_message,
    update_tool_call,
)
from acp.schema import ToolCallStart, ToolKind

from malibu.server.security import extract_command_types, truncate_command_for_display
from malibu.telemetry.logging import get_logger

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Tool call chunk accumulator
# ═══════════════════════════════════════════════════════════════════

class ToolCallAccumulator:
    """Accumulates streaming tool_call_chunks into complete tool call starts."""

    def __init__(self) -> None:
        self._active: dict[str, dict[str, Any]] = {}       # tool_call_id → info
        self._accumulator: dict[int, dict[str, Any]] = {}   # chunk index → {id, name, args_str}

    @property
    def active(self) -> dict[str, dict[str, Any]]:
        return self._active

    def process_chunk(self, message_chunk: Any) -> list[ToolCallStart]:
        """Process a streaming chunk and return any newly completed ToolCallStart objects."""
        if isinstance(message_chunk, str) or not hasattr(message_chunk, "tool_call_chunks"):
            return []
        if not message_chunk.tool_call_chunks:
            return []

        new_starts: list[ToolCallStart] = []

        for chunk in message_chunk.tool_call_chunks:
            chunk_id = chunk.get("id")
            chunk_name = chunk.get("name")
            chunk_args = chunk.get("args", "")
            chunk_index = chunk.get("index", 0)

            # Initialise accumulator for new tool call
            is_new = (
                chunk_index not in self._accumulator
                or chunk_id != self._accumulator[chunk_index].get("id")
            )
            if chunk_id and chunk_name and is_new:
                self._accumulator[chunk_index] = {"id": chunk_id, "name": chunk_name, "args_str": ""}

            if chunk_args and chunk_index in self._accumulator:
                self._accumulator[chunk_index]["args_str"] += chunk_args

        # See if any accumulated calls are ready
        for _idx, acc in list(self._accumulator.items()):
            tool_id = acc.get("id")
            tool_name = acc.get("name")
            args_str = acc.get("args_str", "")

            if tool_id and tool_id not in self._active and args_str:
                try:
                    tool_args = json.loads(args_str)
                    self._active[tool_id] = {"name": tool_name, "args": tool_args}
                    new_starts.append(create_tool_call_start(tool_id, tool_name, tool_args))
                except json.JSONDecodeError:
                    pass  # still accumulating

        return new_starts


# ═══════════════════════════════════════════════════════════════════
# Tool call start factory
# ═══════════════════════════════════════════════════════════════════

_KIND_MAP: dict[str, ToolKind] = {
    "read_file": "read",
    "edit_file": "edit",
    "write_file": "edit",
    "ls": "search",
    "glob": "search",
    "grep": "search",
    "execute": "execute",
}


def create_tool_call_start(tool_id: str, tool_name: str, tool_args: dict[str, Any]) -> ToolCallStart:
    """Create a ToolCallStart from a completed accumulation."""
    tool_kind = _KIND_MAP.get(tool_name, "other")

    if tool_name == "read_file":
        path = tool_args.get("file_path", "")
        return start_tool_call(
            tool_call_id=tool_id, title=f"Read `{path}`" if path else tool_name,
            kind=tool_kind, status="pending", raw_input=tool_args,
        )

    if tool_name == "edit_file":
        path = tool_args.get("file_path", "")
        old_string = tool_args.get("old_string", "")
        new_string = tool_args.get("new_string", "")
        title = f"Edit `{path}`" if path else tool_name
        if path and old_string and new_string:
            diff = tool_diff_content(path=path, new_text=new_string, old_text=old_string)
            return start_edit_tool_call(
                tool_call_id=tool_id, title=title, path=path, content=diff, extra_options=[diff],
            )
        return start_tool_call(tool_call_id=tool_id, title=title, kind=tool_kind, status="pending", raw_input=tool_args)

    if tool_name == "write_file":
        path = tool_args.get("file_path", "")
        return start_tool_call(
            tool_call_id=tool_id, title=f"Write `{path}`" if path else tool_name,
            kind=tool_kind, status="pending", raw_input=tool_args,
        )

    if tool_name == "execute":
        command = tool_args.get("command", "")
        display = truncate_command_for_display(command) if command else "Execute command"
        return start_tool_call(
            tool_call_id=tool_id, title=display, kind=tool_kind, status="pending", raw_input=tool_args,
        )

    return start_tool_call(
        tool_call_id=tool_id, title=tool_name, kind=tool_kind, status="pending", raw_input=tool_args,
    )


# ═══════════════════════════════════════════════════════════════════
# Execute result formatting
# ═══════════════════════════════════════════════════════════════════

def format_execute_result(command: str, result: str) -> str:
    """Format a command execution result with the command as header."""
    display = truncate_command_for_display(command, max_length=120)
    return f"$ {display}\n{result}"
