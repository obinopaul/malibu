"""Collapsible sidebar panel displaying the current plan / todo list."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, Label

try:
    from acp.schema import AgentPlanUpdate
except Exception:  # pragma: no cover — optional dependency
    AgentPlanUpdate = None  # type: ignore[assignment,misc]


_STATUS_ICONS: dict[str, str] = {
    "completed": "\u2713",     # checkmark
    "in_progress": "\u2192",   # right arrow
    "pending": "\u25cb",       # circle
}


class PlanPanel(Widget):
    """A collapsible sidebar that shows the current plan entries.

    Toggle visibility with the ``p`` key (configurable via ``BINDINGS``).
    Call ``update_plan()`` to replace the displayed entries.
    """

    BINDINGS = [
        Binding("p", "toggle_panel", "Toggle plan panel", show=False),
    ]

    DEFAULT_CSS = """
    PlanPanel {
        width: 30;
        dock: right;
        background: $surface;
        border-left: solid $primary;
        padding: 1;
        display: block;
    }

    PlanPanel.hidden {
        display: none;
    }

    #plan-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .plan-entry {
        margin: 0;
        padding: 0 1;
    }

    .plan-entry-completed {
        color: $success;
    }

    .plan-entry-in_progress {
        color: $warning;
        text-style: bold;
    }

    .plan-entry-pending {
        color: #5C6370;
    }
    """

    visible: reactive[bool] = reactive(True)

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._entries: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Label("[bold]Plan[/bold]", id="plan-title")
        yield Vertical(id="plan-items")

    # ---- public API ----

    def update_plan(self, entries: list[dict[str, Any]]) -> None:
        """Replace the displayed plan entries.

        Each entry should have ``content`` (str) and ``status`` (str) keys.
        Valid statuses: ``completed``, ``in_progress``, ``pending``.
        """
        self._entries = list(entries)
        self._rebuild_items()

    def action_toggle_panel(self) -> None:
        """Toggle the panel between visible and hidden."""
        self.visible = not self.visible

    def toggle(self) -> None:
        """Alias for ``action_toggle_panel`` used by ChatScreen."""
        self.action_toggle_panel()

    def set_plan(self, update: Any) -> None:
        """Accept an ``AgentPlanUpdate`` and convert to dict entries.

        This bridges the ACP schema type used by ChatScreen to the
        generic ``update_plan(entries)`` method.
        """
        entries: list[dict[str, Any]] = []
        raw_entries = getattr(update, "entries", None) or []
        for entry in raw_entries:
            entries.append({
                "content": getattr(entry, "content", str(entry)),
                "status": getattr(entry, "status", "pending"),
            })
        self.update_plan(entries)

    # ---- watchers ----

    def _watch_visible(self, value: bool) -> None:
        if value:
            self.remove_class("hidden")
        else:
            self.add_class("hidden")

    # ---- internals ----

    def _rebuild_items(self) -> None:
        """Clear and re-mount plan entry widgets."""
        try:
            container = self.query_one("#plan-items", Vertical)
        except Exception:
            return

        container.remove_children()

        for entry in self._entries:
            content = entry.get("content", "")
            status = entry.get("status", "pending")
            icon = _STATUS_ICONS.get(status, "\u25cb")
            css_class = f"plan-entry plan-entry-{status}"
            widget = Static(f"{icon} {content}", classes=css_class)
            container.mount(widget)
