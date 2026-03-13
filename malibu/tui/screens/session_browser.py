"""SessionBrowserScreen — modal screen for listing and selecting sessions.

Presents a :class:`DataTable` of existing sessions and lets the user
resume one, start a new session, or cancel.

Returns the selected ``session_id`` (or ``None`` for new / cancel) via
:meth:`~textual.screen.ModalScreen.dismiss`.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Label, Static


class SessionBrowserScreen(ModalScreen[str | None]):
    """Modal overlay for browsing and selecting agent sessions.

    Parameters
    ----------
    sessions:
        A list of session dicts, each expected to have at least:
        ``id``, ``title``, ``cwd``, ``mode``.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("n", "new_session", "New Session", show=True),
        Binding("enter", "select_session", "Select", show=True),
    ]

    DEFAULT_CSS = """
    SessionBrowserScreen {
        align: center middle;
        background: #0A0E14 80%;
    }
    #browser-container {
        width: 90;
        height: 24;
        border: round #0077B6;
        background: #1A1F2B;
        padding: 1 2;
    }
    #browser-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    #browser-hint {
        color: #5C6370;
        text-align: center;
        margin-top: 1;
    }
    DataTable {
        height: 1fr;
    }
    """

    def __init__(self, sessions: list[dict[str, Any]] | None = None) -> None:
        super().__init__()
        self._sessions = sessions or []

    def compose(self) -> ComposeResult:
        with Vertical(id="browser-container"):
            yield Label("Sessions", id="browser-title")
            yield DataTable(id="session-table")
            yield Static(
                "[dim]Enter[/] select  |  [dim]n[/] new session  |  [dim]Esc[/] cancel",
                id="browser-hint",
            )
            yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#session-table", DataTable)
        table.add_columns("ID", "Title", "CWD", "Mode")
        table.cursor_type = "row"

        for session in self._sessions:
            sid = str(session.get("id", ""))
            title = str(session.get("title", ""))
            cwd = str(session.get("cwd", ""))
            mode = str(session.get("mode", ""))
            table.add_row(sid, title, cwd, mode, key=sid)

        if not self._sessions:
            table.add_row("", "(no sessions)", "", "", key="__empty__")

    # -- Actions -----------------------------------------------------------

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_new_session(self) -> None:
        self.dismiss(None)

    def action_select_session(self) -> None:
        table = self.query_one("#session-table", DataTable)
        if table.cursor_row is not None and self._sessions:
            row_key = table.get_row_at(table.cursor_row)
            # First column is the session id
            session_id = str(row_key[0]) if row_key else None
            if session_id:
                self.dismiss(session_id)
                return
        self.dismiss(None)

    # -- Double-click / Enter on row ---------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self._sessions and event.row_key and str(event.row_key.value) != "__empty__":
            self.dismiss(str(event.row_key.value))
