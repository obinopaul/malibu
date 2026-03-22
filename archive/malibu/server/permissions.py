"""Permission state and tool-title helpers for Malibu HITL flows."""

from __future__ import annotations

from typing import Any

from acp.schema import PermissionOption, ToolCallUpdate

from malibu.server.plans import all_tasks_completed
from malibu.server.security import extract_command_types, truncate_command_for_display


class PermissionManager:
    """Track always-allow state and approved plans per session."""

    def __init__(self) -> None:
        self._allowed_command_types: dict[str, set[tuple[str, str | None]]] = {}
        self._session_plans: dict[str, list[dict[str, Any]]] = {}

    def is_auto_approved(self, session_id: str, tool_name: str, tool_args: dict[str, Any]) -> bool:
        if tool_name == "write_todos":
            existing = self._session_plans.get(session_id, [])
            if existing and not all_tasks_completed(existing):
                self._session_plans[session_id] = tool_args.get("todos", [])
                return True
            return False

        allowed = self._allowed_command_types.get(session_id, set())
        if tool_name == "execute":
            command = tool_args.get("command", "")
            signatures = extract_command_types(command)
            return bool(signatures) and all(("execute", signature) in allowed for signature in signatures)
        return (tool_name, None) in allowed

    def register_always_allow(self, session_id: str, tool_name: str, tool_args: dict[str, Any]) -> None:
        allowed = self._allowed_command_types.setdefault(session_id, set())
        if tool_name == "execute":
            for signature in extract_command_types(tool_args.get("command", "")):
                allowed.add(("execute", signature))
            return
        allowed.add((tool_name, None))

    def approve_plan(self, session_id: str, tool_args: dict[str, Any]) -> None:
        self._session_plans[session_id] = tool_args.get("todos", [])

    def clear_plan(self, session_id: str) -> None:
        self._session_plans[session_id] = []

    def build_permission_options(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        allowed_decisions: list[str] | None = None,
    ) -> list[PermissionOption]:
        allowed_decisions = allowed_decisions or ["approve", "reject"]
        options: list[PermissionOption] = [
            PermissionOption(option_id="approve", name="Approve", kind="allow_once"),
            PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
        ]
        if "edit" in allowed_decisions:
            options.insert(1, PermissionOption(option_id="edit", name="Edit input", kind="allow_once"))
        desc = tool_name
        if tool_name == "execute":
            command = tool_args.get("command", "")
            signatures = extract_command_types(command)
            if signatures:
                desc = ", ".join(dict.fromkeys(signatures))
        options.append(
            PermissionOption(
                option_id="approve_always",
                name=f"Always allow {desc}",
                kind="allow_always",
            )
        )
        return options

    def build_title(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        if tool_name == "write_todos":
            return "Review plan"
        if tool_name in {"edit_file", "write_file"}:
            return f"{tool_name.replace('_', ' ').title()}: {tool_args.get('file_path', 'file')}"
        if tool_name == "execute":
            command = tool_args.get("command", "")
            display = truncate_command_for_display(command) if command else "Execute command"
            return f"Execute: {display}"
        return tool_name.replace("_", " ").title()

    def build_tool_call_update(self, tool_call_id: str, tool_name: str, tool_args: dict[str, Any]) -> ToolCallUpdate:
        return ToolCallUpdate(
            tool_call_id=tool_call_id,
            title=self.build_title(tool_name, tool_args),
            raw_input=tool_args,
        )
