"""Autocomplete popup for the chat composer."""

from __future__ import annotations

from rich.panel import Panel
from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Static


class AutocompletePopup(Static):
    """Simple popup that mirrors the chat input completion state."""

    class SelectionRequested(Message):
        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    DEFAULT_CSS = """
    AutocompletePopup {
        display: none;
        margin: 0 1 0 1;
        width: 1fr;
        height: auto;
    }
    """

    def __init__(self, *, max_visible_rows: int = 6) -> None:
        super().__init__(id="autocomplete-popup")
        self._items: list[tuple[str, str]] = []
        self._selected = 0
        self._max_visible_rows = max_visible_rows
        self._window_start = 0
        self._visible_count = 0

    def update_items(self, items: list[tuple[str, str]], selected: int | None) -> None:
        self._items = list(items)
        self._selected = selected or 0
        self.display = bool(items)
        if not items:
            self.update("")
            return
        self._refresh_popup()

    def refresh_theme(self) -> None:
        if self._items:
            self._refresh_popup()

    def _refresh_popup(self) -> None:
        theme = getattr(self.app, "current_theme", None)
        accent = getattr(theme, "accent", None) or getattr(theme, "primary", None) or "#38bdf8"
        foreground = getattr(theme, "foreground", None) or "#e2e8f0"
        muted = getattr(theme, "variables", {}).get("foreground-muted", "#94a3b8") if theme else "#94a3b8"
        panel = getattr(theme, "panel", None) or "#1f2937"
        start = 0
        if len(self._items) > self._max_visible_rows:
            start = max(0, min(self._selected - self._max_visible_rows + 1, len(self._items) - self._max_visible_rows))
        self._window_start = start
        visible_items = self._items[start : start + self._max_visible_rows]
        self._visible_count = len(visible_items)
        lines: list[Text] = []
        for visible_index, (label, meta) in enumerate(visible_items, start=start):
            active = visible_index == self._selected
            line = Text()
            line.append(">" if active else " ", style=accent if active else muted)
            line.append(f" {label}", style=f"bold {foreground}" if active else foreground)
            if meta:
                line.append(f"  {meta}", style=muted)
            lines.append(line)
        if len(self._items) > self._max_visible_rows:
            lines.append(
                Text(
                    f"{self._selected + 1}/{len(self._items)}  use ↑ ↓ to scroll",
                    style=muted,
                )
            )
        self.update(
            Panel(
                Text("\n").join(lines),
                border_style=accent,
                title="Suggestions",
                style=f"on {panel}",
                padding=(0, 1),
            )
        )

    def on_click(self, event: events.Click) -> None:
        if not self._items:
            return
        row = event.y - 1
        if 0 <= row < self._visible_count:
            self.post_message(self.SelectionRequested(self._window_start + row))
