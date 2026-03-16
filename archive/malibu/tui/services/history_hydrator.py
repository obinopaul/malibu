"""Replay persisted events through the live display path."""

from __future__ import annotations

from typing import Any


class HistoryHydrator:
    """Hydrate saved events using the same processor used for live updates."""

    def __init__(self, processor: Any) -> None:
        self._processor = processor

    def hydrate(self, events: list[dict[str, Any]]) -> None:
        for event in events:
            kind = event.get("kind")
            payload = event.get("payload", {})
            if kind == "session_update":
                self._processor.apply_session_update(payload, from_history=True)
            elif kind == "tui_event":
                self._processor.apply_tui_event(payload, from_history=True)
