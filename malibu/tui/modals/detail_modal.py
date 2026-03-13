"""Fallback detail and JSON editor modal surfaces."""

from __future__ import annotations

import json
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea


class JsonEditorModal(ModalScreen[dict[str, Any] | None]):
    """Editable JSON modal for tool argument review."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("ctrl+s", "save", "Save", show=True),
    ]

    DEFAULT_CSS = """
    JsonEditorModal {
        align: center middle;
        background: #020617 80%;
    }
    #json-editor-dialog {
        width: 90;
        height: 28;
        padding: 1 2;
        background: #0f172a;
        border: round #38bdf8;
    }
    #json-editor-title {
        margin-bottom: 1;
        text-style: bold;
    }
    #json-editor-text {
        height: 1fr;
        margin-bottom: 1;
    }
    """

    def __init__(self, *, title: str, value: Any) -> None:
        super().__init__()
        self._title = title
        self._value = value

    def compose(self) -> ComposeResult:
        with Vertical(id="json-editor-dialog"):
            yield Label(self._title, id="json-editor-title")
            yield TextArea(json.dumps(self._value, indent=2, default=str), id="json-editor-text")
            yield Button("Save", id="save-json", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-json":
            self._submit()

    def _submit(self) -> None:
        text = self.query_one("#json-editor-text", TextArea).text
        try:
            self.dismiss(json.loads(text))
        except json.JSONDecodeError:
            self.notify("Invalid JSON", severity="error")
