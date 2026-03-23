"""Modal viewer for connected MCP servers and their available tools."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label


class McpViewerModal(ModalScreen[None]):
    """A modal that lists connected MCP servers and their tools in a table.

    Dismiss with **Escape**.

    Constructor args:
        servers: A list of dicts, each with ``name`` (str) and ``tools``
                 (list of str or list of dicts with a ``name`` key).
    """

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close", show=True),
    ]

    DEFAULT_CSS = """
    McpViewerModal {
        align: center middle;
    }

    #mcp-dialog {
        width: 80;
        max-height: 80%;
        border: heavy $primary;
        background: $surface;
        padding: 1 2;
    }

    #mcp-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #mcp-table {
        height: auto;
        max-height: 40;
    }
    """

    def __init__(
        self,
        servers: list[dict[str, Any]] | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._servers = servers or []

    def compose(self) -> ComposeResult:
        with Vertical(id="mcp-dialog"):
            yield Label("[bold]MCP Servers & Tools[/bold]", id="mcp-title")
            yield DataTable(id="mcp-table")

    def on_mount(self) -> None:
        """Populate the table once the widget tree is ready."""
        table = self.query_one("#mcp-table", DataTable)
        table.add_columns("Server", "Tool")

        for server in self._servers:
            server_name = server.get("name", "<unnamed>")
            tools = server.get("tools", [])
            if not tools:
                table.add_row(server_name, "(no tools)")
                continue
            for i, tool in enumerate(tools):
                tool_name = tool if isinstance(tool, str) else tool.get("name", str(tool))
                # Show server name only on the first row of each group
                display_server = server_name if i == 0 else ""
                table.add_row(display_server, tool_name)

    def action_dismiss_modal(self) -> None:
        """Close the modal."""
        self.dismiss(None)
