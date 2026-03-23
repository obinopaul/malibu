"""Tool output buffering helpers."""

from __future__ import annotations

from typing import Any


class ConsoleBufferManager:
    """Store tool output and generate collapsed previews."""

    def __init__(self, *, preview_lines: int = 12, preview_chars: int = 1200) -> None:
        self._preview_lines = preview_lines
        self._preview_chars = preview_chars
        self._buffers: dict[str, str] = {}

    def update(self, tool_call_id: str, text: str) -> str:
        """Replace the current buffered text for a tool call."""
        self._buffers[tool_call_id] = text
        return text

    def get(self, tool_call_id: str) -> str:
        return self._buffers.get(tool_call_id, "")

    def clear(self, tool_call_id: str) -> None:
        self._buffers.pop(tool_call_id, None)

    def preview(self, tool_call_id: str, *, fallback: str = "") -> tuple[str, bool]:
        """Return a collapsed preview and whether truncation occurred."""
        text = self._buffers.get(tool_call_id, fallback)
        if not text:
            return "", False
        truncated = False
        lines = text.splitlines()
        if len(lines) > self._preview_lines:
            text = "\n".join(lines[: self._preview_lines])
            truncated = True
        if len(text) > self._preview_chars:
            text = text[: self._preview_chars].rstrip()
            truncated = True
        return text, truncated

    @staticmethod
    def stringify_content(content: Any) -> str:
        """Best-effort text extraction from ACP tool content payloads."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if hasattr(item, "text"):
                    parts.append(str(getattr(item, "text")))
                    continue
                if isinstance(item, dict):
                    if "text" in item:
                        parts.append(str(item.get("text", "")))
                    elif "content" in item and isinstance(item["content"], list):
                        parts.append(ConsoleBufferManager.stringify_content(item["content"]))
                    else:
                        parts.append(str(item))
            return "\n".join(part for part in parts if part)
        return str(content)
