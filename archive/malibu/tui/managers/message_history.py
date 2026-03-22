"""Input and replay history for the Malibu TUI."""

from __future__ import annotations

from typing import Any


class MessageHistory:
    """Track input history and persisted replay events."""

    def __init__(self) -> None:
        self._inputs: list[str] = []
        self._cursor = 0
        self._draft = ""
        self._events: list[dict[str, Any]] = []

    def record_input(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        self._inputs.append(cleaned)
        self._cursor = len(self._inputs)
        self._draft = ""

    def previous_input(self, current_text: str) -> str | None:
        if not self._inputs:
            return None
        if self._cursor == len(self._inputs):
            self._draft = current_text
        self._cursor = max(0, self._cursor - 1)
        return self._inputs[self._cursor]

    def next_input(self) -> str | None:
        if not self._inputs:
            return None
        if self._cursor >= len(self._inputs) - 1:
            self._cursor = len(self._inputs)
            return self._draft
        self._cursor += 1
        return self._inputs[self._cursor]

    def replace_events(self, events: list[dict[str, Any]]) -> None:
        self._events = list(events)

    def append_event(self, event: dict[str, Any]) -> None:
        self._events.append(event)

    def snapshot_events(self) -> list[dict[str, Any]]:
        return list(self._events)
