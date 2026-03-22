"""Tool-specific renderers for displaying tool call results in the TUI."""

from __future__ import annotations

import json
from typing import Any, Callable


# Type alias for a render function: (tool_input, tool_output) -> str
RenderFunc = Callable[[dict[str, Any], Any], str]


def render_edit_file(tool_input: dict[str, Any], tool_output: Any) -> str:
    """Render an edit_file tool call as a diff-like display."""
    file_path = tool_input.get("file_path", "<unknown>")
    old = tool_input.get("old_string", "")
    new = tool_input.get("new_string", "")

    lines: list[str] = [f"--- {file_path}", f"+++ {file_path}"]
    for line in old.splitlines():
        lines.append(f"- {line}")
    for line in new.splitlines():
        lines.append(f"+ {line}")
    return "\n".join(lines)


def render_execute(tool_input: dict[str, Any], tool_output: Any) -> str:
    """Render a command execution tool call."""
    command = tool_input.get("command", "")
    output_text = ""
    if isinstance(tool_output, str):
        output_text = tool_output
    elif isinstance(tool_output, dict):
        output_text = tool_output.get("stdout", "") or tool_output.get("output", "")

    lines = [f"$ {command}"]
    if output_text:
        lines.append(output_text)
    return "\n".join(lines)


def render_write_file(tool_input: dict[str, Any], tool_output: Any) -> str:
    """Render a write_file tool call showing path and content size."""
    file_path = tool_input.get("file_path", "<unknown>")
    content = tool_input.get("content", "")
    size = len(content.encode("utf-8")) if isinstance(content, str) else 0
    return f"Wrote {file_path} ({size} bytes)"


def render_default(tool_input: dict[str, Any], tool_output: Any) -> str:
    """Fallback renderer — generic JSON display."""
    parts: list[str] = []
    try:
        parts.append(json.dumps(tool_input, indent=2, default=str))
    except Exception:
        parts.append(str(tool_input))

    if tool_output is not None:
        parts.append("--- output ---")
        try:
            parts.append(json.dumps(tool_output, indent=2, default=str))
        except Exception:
            parts.append(str(tool_output))

    return "\n".join(parts)


class ToolRendererRegistry:
    """Registry mapping tool names to specialised render functions.

    Usage::

        registry = ToolRendererRegistry()
        text = registry.render("edit_file", tool_input, tool_output)
    """

    def __init__(self) -> None:
        self._renderers: dict[str, RenderFunc] = {
            "edit_file": render_edit_file,
            "Edit": render_edit_file,
            "execute": render_execute,
            "Bash": render_execute,
            "write_file": render_write_file,
            "Write": render_write_file,
        }

    def register(self, tool_name: str, func: RenderFunc) -> None:
        """Register a custom render function for *tool_name*."""
        self._renderers[tool_name] = func

    def render(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_output: Any = None,
    ) -> str:
        """Render a tool call using the registered (or default) renderer."""
        func = self._renderers.get(tool_name, render_default)
        return func(tool_input, tool_output)
