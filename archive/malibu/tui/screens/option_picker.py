"""Reusable modal picker for short selectable option lists."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, Static


@dataclass(frozen=True, slots=True)
class OptionPickerItem:
    """Single selectable option row."""

    value: str
    label: str
    description: str = ""


class OptionPickerScreen(ModalScreen[str | None]):
    """Filterable modal for selecting one option."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("enter", "select_option", "Select", show=True),
    ]

    DEFAULT_CSS = """
    OptionPickerScreen {
        align: center middle;
        background: #14110F 84%;
    }
    #option-picker-dialog {
        width: 82;
        height: 24;
        padding: 1 2;
        border: round #D7A77A;
        background: #27211E;
    }
    #option-picker-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #option-picker-subtitle {
        color: #AA9988;
        margin-bottom: 1;
    }
    #option-picker-filter {
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        *,
        title: str,
        subtitle: str,
        items: list[OptionPickerItem],
    ) -> None:
        super().__init__()
        self._title = title
        self._subtitle = subtitle
        self._items = items
        self._filtered = list(items)

    def compose(self) -> ComposeResult:
        with Vertical(id="option-picker-dialog"):
            yield Label(self._title, id="option-picker-title")
            yield Static(self._subtitle, id="option-picker-subtitle")
            yield Input(placeholder="Filter options", id="option-picker-filter")
            yield DataTable(id="option-picker-table")

    def on_mount(self) -> None:
        table = self.query_one("#option-picker-table", DataTable)
        table.add_columns("Option", "Description")
        table.cursor_type = "row"
        self._rebuild_table()
        self.query_one("#option-picker-filter", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.strip().lower()
        if not query:
            self._filtered = list(self._items)
        else:
            self._filtered = [
                item
                for item in self._items
                if query in item.label.lower() or query in item.description.lower()
            ]
        self._rebuild_table()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select_option(self) -> None:
        table = self.query_one("#option-picker-table", DataTable)
        if table.row_count == 0:
            self.dismiss(None)
            return
        row = table.get_row_at(table.cursor_row or 0)
        value = str(row[0]) if row else None
        self.dismiss(value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row = self.query_one("#option-picker-table", DataTable).get_row(event.row_key)
        self.dismiss(str(row[0]) if row else None)

    def _rebuild_table(self) -> None:
        table = self.query_one("#option-picker-table", DataTable)
        table.clear(columns=False)
        for item in self._filtered:
            table.add_row(item.value, item.description, key=item.value)
