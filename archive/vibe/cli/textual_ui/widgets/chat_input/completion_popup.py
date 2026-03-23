from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

VISIBLE_WINDOW = 6
MAX_DESCRIPTION_CHARS = 50


def _truncate_description(desc: str) -> str:
    """Truncate a description to MAX_DESCRIPTION_CHARS, adding ellipsis if needed."""
    if len(desc) <= MAX_DESCRIPTION_CHARS:
        return desc
    return desc[: MAX_DESCRIPTION_CHARS - 1].rstrip() + "…"


def _scrollbar_chars(total: int, window: int, start: int) -> list[str]:
    """Return a list of characters representing a vertical scrollbar track.

    Each entry corresponds to one visible row.  The 'thumb' (█) shows
    which portion of the full list is currently visible; the rest of the
    track uses a dim bar (│).
    """
    if total <= window:
        return ["" for _ in range(window)]

    # thumb size: at least 1 row
    thumb = max(1, round(window * window / total))
    # thumb position
    max_start = total - window
    if max_start > 0:
        thumb_top = round(start / max_start * (window - thumb))
    else:
        thumb_top = 0
    thumb_bottom = thumb_top + thumb

    chars: list[str] = []
    for i in range(window):
        if thumb_top <= i < thumb_bottom:
            chars.append("█")
        else:
            chars.append("│")
    return chars


class CompletionPopup(Static):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", id="completion-popup", **kwargs)
        self.styles.display = "none"
        self.can_focus = False

    def update_suggestions(
        self, suggestions: list[tuple[str, str]], selected: int
    ) -> None:
        if not suggestions:
            self.hide()
            return

        total = len(suggestions)
        window = min(VISIBLE_WINDOW, total)

        # Compute the visible slice so the selected item is always in view.
        half = window // 2
        start = selected - half
        if start < 0:
            start = 0
        end = start + window
        if end > total:
            end = total
            start = max(0, end - window)

        scrollbar = _scrollbar_chars(total, window, start)

        text = Text()
        row = 0
        for idx in range(start, end):
            if row > 0:
                text.append("\n")

            label, description = suggestions[idx]

            label_style = "bold reverse" if idx == selected else "bold"
            description_style = "italic" if idx == selected else "dim"

            text.append(label, style=label_style)
            if description:
                text.append("  ")
                text.append(
                    _truncate_description(description), style=description_style
                )

            # Append scrollbar character at end of row
            if total > window:
                text.append(" ")
                text.append(scrollbar[row], style="dim")

            row += 1

        self.update(text)
        self.show()

    def hide(self) -> None:
        self.update("")
        self.styles.display = "none"

    def show(self) -> None:
        self.styles.display = "block"
