"""Collapsible todo and plan rail."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, Static


class PlanPanel(Widget):
    """Right-side plan rail with compact todo rendering."""

    DEFAULT_CSS = """
    PlanPanel {
        width: 26;
        min-width: 22;
        max-width: 30;
        background: $panel;
        border-left: solid $panel-lighten-1;
        padding: 1;
    }
    PlanPanel.-hidden {
        display: none;
    }
    #plan-panel-title {
        margin-bottom: 1;
        color: $accent;
        text-style: bold;
    }
    #plan-panel-items {
        height: 1fr;
    }
    .plan-entry {
        margin: 0 0 1 0;
        padding: 0 1;
    }
    """

    visible: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__(id="plan-panel")
        self._entries: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Label("Plan", id="plan-panel-title")
        yield VerticalScroll(id="plan-panel-items")

    def toggle(self) -> None:
        self.visible = not self.visible

    def set_plan(self, update: Any) -> None:
        raw_entries = getattr(update, "entries", None) or []
        self._entries = [
            {
                "content": getattr(entry, "content", str(entry)),
                "status": getattr(entry, "status", "pending"),
            }
            for entry in raw_entries
        ]
        self.visible = bool(self._entries)
        self._rebuild()

    def clear_plan(self) -> None:
        self._entries = []
        self.visible = False
        self._rebuild()

    def refresh_theme(self) -> None:
        self._rebuild()

    def watch_visible(self) -> None:
        if self.visible:
            self.remove_class("-hidden")
        else:
            self.add_class("-hidden")

    def _rebuild(self) -> None:
        container = self.query_one("#plan-panel-items", VerticalScroll)
        container.remove_children()
        title = self.query_one("#plan-panel-title", Label)
        title.update("Plan" if not self._entries else f"Plan ({len(self._entries)})")
        if not self._entries:
            container.mount(Static("Plan updates will appear here.", classes="plan-entry"))
            return
        for index, entry in enumerate(self._entries, start=1):
            icon = {
                "completed": "[green]x[/]",
                "in_progress": "[yellow]>[/]",
                "pending": "[dim]o[/]",
            }.get(entry["status"], "[dim]o[/]")
            text = f"{icon} {index}. {entry['content']}"
            container.mount(Static(text, classes="plan-entry"))
