"""Permission handling — bridges LangGraph interrupts to ACP request_permission.

Manages:
  - Interrupt → permission option mapping
  - Per-session command type auto-approval (allowlists)
  - Plan approval/rejection with feedback
  - 'Always allow' escalation tracking
"""

from __future__ import annotations

from typing import Any

from acp.schema import PermissionOption, ToolCallUpdate

from malibu.server.plans import all_tasks_completed, build_empty_plan, format_plan_text
from malibu.server.security import extract_command_types, truncate_command_for_display
from malibu.telemetry.logging import get_logger

log = get_logger(__name__)


class PermissionManager:
    """Per-session permission state and interrupt-to-ACP translation."""

    def __init__(self) -> None:
        # session_id → set of (tool_name, command_signature|None)
        self._allowed_command_types: dict[str, set[tuple[str, str | None]]] = {}
        # session_id → list of todo dicts (the approved plan)
        self._session_plans: dict[str, list[dict[str, Any]]] = {}

    def is_auto_approved(self, session_id: str, tool_name: str, tool_args: dict[str, Any]) -> bool:
        """Check if a tool call should be auto-approved based on session allowlist."""
        # Auto-approve write_todos when updating an in-progress plan
        if tool_name == "write_todos":
            if session_id in self._session_plans:
                existing = self._session_plans[session_id]
                if not all_tasks_completed(existing):
                    # Plan in progress → auto-approve updates
                    todos = tool_args.get("todos", [])
                    self._session_plans[session_id] = todos
                    return True
            return False

        allowed = self._allowed_command_types.get(session_id, set())
        if not allowed:
            return False

        # Execute commands check against extracted command signatures
        if tool_name == "execute":
            command = tool_args.get("command", "")
            sigs = extract_command_types(command)
            if sigs and all(("execute", sig) in allowed for sig in sigs):
                return True
            return False

        # Generic tool name check
        return (tool_name, None) in allowed

    def register_always_allow(self, session_id: str, tool_name: str, tool_args: dict[str, Any]) -> None:
        """Register 'always allow' for a tool/command type."""
        if session_id not in self._allowed_command_types:
            self._allowed_command_types[session_id] = set()

        if tool_name == "execute":
            command = tool_args.get("command", "")
            for sig in extract_command_types(command):
                self._allowed_command_types[session_id].add(("execute", sig))
        else:
            self._allowed_command_types[session_id].add((tool_name, None))

    def approve_plan(self, session_id: str, tool_args: dict[str, Any]) -> None:
        """Register a plan as approved for future auto-approval of updates."""
        self._session_plans[session_id] = tool_args.get("todos", [])

    def clear_plan(self, session_id: str) -> None:
        """Clear the stored plan for a session."""
        self._session_plans[session_id] = []

    def build_permission_options(self, tool_name: str, tool_args: dict[str, Any]) -> list[PermissionOption]:
        """Build the permission option set for a given tool call."""
        desc = tool_name
        if tool_name == "execute":
            command = tool_args.get("command", "")
            sigs = extract_command_types(command)
            if sigs:
                desc = ", ".join(f"`{s}`" for s in dict.fromkeys(sigs))

        return [
            PermissionOption(option_id="approve", name="Approve", kind="allow_once"),
            PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
            PermissionOption(option_id="approve_always", name=f"Always allow {desc}", kind="allow_always"),
        ]

    def build_tool_call_update(self, tool_call_id: str, tool_name: str, tool_args: dict[str, Any]) -> ToolCallUpdate:
        """Build a ToolCallUpdate for the permission prompt."""
        if tool_name == "write_todos":
            title = "Review Plan"
        elif tool_name == "edit_file":
            title = f"Edit `{tool_args.get('file_path', 'file')}`"
        elif tool_name == "write_file":
            title = f"Write `{tool_args.get('file_path', 'file')}`"
        elif tool_name == "execute":
            cmd = tool_args.get("command", "")
            display = truncate_command_for_display(cmd) if cmd else "Execute command"
            title = f"Execute: `{display}`"
        else:
            title = tool_name

        return ToolCallUpdate(tool_call_id=tool_call_id, title=title, raw_input=tool_args)
