"""Command palette for slash commands."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label


class CommandPaletteScreen(ModalScreen[str | None]):
    """Filterable slash-command picker."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("enter", "select_command", "Select", show=True),
    ]

    DEFAULT_CSS = """
    CommandPaletteScreen {
        align: center middle;
        background: #020617 82%;
    }
    #command-palette-dialog {
        width: 80;
        height: 24;
        padding: 1 2;
        border: round #38bdf8;
        background: #0f172a;
    }
    #command-palette-filter {
        margin-bottom: 1;
    }
    """

    def __init__(self, commands: list[tuple[str, str]]) -> None:
        super().__init__()
        self._commands = commands
        self._filtered = commands

    def compose(self) -> ComposeResult:
        with Vertical(id="command-palette-dialog"):
            yield Label("Command Palette")
            yield Input(placeholder="Filter commands", id="command-palette-filter")
            yield DataTable(id="command-palette-table")

    def on_mount(self) -> None:
        table = self.query_one("#command-palette-table", DataTable)
        table.add_columns("Command", "Description")
        table.cursor_type = "row"
        self._rebuild_table()
        self.query_one(Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.strip().lower()
        if not query:
            self._filtered = self._commands
        else:
            self._filtered = [
                item
                for item in self._commands
                if query in item[0].lower() or query in item[1].lower()
            ]
        self._rebuild_table()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select_command(self) -> None:
        table = self.query_one("#command-palette-table", DataTable)
        if table.row_count == 0:
            self.dismiss(None)
            return
        row = table.get_row_at(table.cursor_row or 0)
        self.dismiss(str(row[0]) if row else None)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row = self.query_one("#command-palette-table", DataTable).get_row(event.row_key)
        self.dismiss(str(row[0]) if row else None)

    def _rebuild_table(self) -> None:
        table = self.query_one("#command-palette-table", DataTable)
        table.clear(columns=False)
        for command, description in self._filtered:
            table.add_row(command, description, key=command)
