"""Modal dialog for tool-call approval / permission decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Label


@dataclass(frozen=True)
class ApprovalResult:
    """Payload returned when the modal is dismissed.

    Attributes:
        action: One of ``"approve"``, ``"reject"``, ``"always_allow"``, ``"cancel"``.
        tool_name: The tool this decision applies to.
    """

    action: str
    tool_name: str


class ApprovalModal(ModalScreen[ApprovalResult]):
    """A modal that asks the user to approve, reject, or always-allow a tool call.

    Constructor args:
        tool_name: Name of the tool requesting approval.
        tool_input: The input payload to display as a preview.
        permission_options: Optional dict of extra permission metadata.
    """

    BINDINGS = [
        Binding("y", "approve", "Approve", show=True),
        Binding("n", "reject", "Reject", show=True),
        Binding("a", "always_allow", "Always Allow", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    DEFAULT_CSS = """
    ApprovalModal {
        align: center middle;
    }

    #approval-dialog {
        width: 70;
        max-height: 80%;
        border: heavy $primary;
        background: $surface;
        padding: 1 2;
    }

    #approval-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #approval-preview {
        max-height: 20;
        overflow-y: auto;
        margin-bottom: 1;
        padding: 1;
        background: $panel;
    }

    #approval-buttons {
        height: 3;
        align: center middle;
    }

    #approval-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        tool_name: str,
        tool_input: Any = None,
        permission_options: dict[str, Any] | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._tool_name = tool_name
        self._tool_input = tool_input
        self._permission_options = permission_options or {}

    # ---- layout ----

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-dialog"):
            yield Label(f"Tool: [bold]{self._tool_name}[/bold]", id="approval-title")
            yield Static(self._format_preview(), id="approval-preview")
            yield Static(
                "[y] Approve  [n] Reject  [a] Always Allow  [Esc] Cancel",
                id="approval-hint",
            )
            with Horizontal(id="approval-buttons"):
                yield Button("Approve (y)", variant="success", id="btn-approve")
                yield Button("Reject (n)", variant="error", id="btn-reject")
                yield Button("Always (a)", variant="warning", id="btn-always")

    # ---- helpers ----

    def _format_preview(self) -> str:
        """Return a human-readable representation of the tool input."""
        if self._tool_input is None:
            return "(no input)"
        if isinstance(self._tool_input, str):
            return self._tool_input
        try:
            import json
            return json.dumps(self._tool_input, indent=2, default=str)
        except Exception:
            return str(self._tool_input)

    def _make_result(self, action: str) -> ApprovalResult:
        return ApprovalResult(action=action, tool_name=self._tool_name)

    # ---- actions (key bindings) ----

    def action_approve(self) -> None:
        self.dismiss(self._make_result("approve"))

    def action_reject(self) -> None:
        self.dismiss(self._make_result("reject"))

    def action_always_allow(self) -> None:
        self.dismiss(self._make_result("always_allow"))

    def action_cancel(self) -> None:
        self.dismiss(self._make_result("cancel"))

    # ---- button handlers ----

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_map = {
            "btn-approve": "approve",
            "btn-reject": "reject",
            "btn-always": "always_allow",
        }
        action = button_map.get(event.button.id or "", "cancel")
        self.dismiss(self._make_result(action))
