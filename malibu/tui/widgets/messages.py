"""Chat message widgets for the Malibu TUI.

Each message type inherits from ``BaseMessage`` and provides its own
default CSS styling.
"""

from __future__ import annotations

from datetime import datetime, timezone

from textual.reactive import reactive
from textual.widgets import Static, Markdown


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class BaseMessage(Static):
    """Common base for all message widgets. Stores a creation timestamp."""

    DEFAULT_CSS = """
    BaseMessage {
        width: 1fr;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    timestamp: reactive[str] = reactive("")

    def __init__(
        self,
        content: str = "",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(content, name=name, id=id, classes=classes)
        self.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class UserMessage(BaseMessage):
    """Displays user input with a ``You:`` label and blue styling."""

    DEFAULT_CSS = """
    UserMessage {
        width: 1fr;
        padding: 0 1;
        margin: 0 0 1 0;
        color: $text;
        background: $primary 15%;
    }
    """

    def __init__(
        self,
        text: str,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(f"[bold blue]You:[/bold blue] {text}", name=name, id=id, classes=classes)


# ---------------------------------------------------------------------------
# Assistant (streaming markdown)
# ---------------------------------------------------------------------------

class AssistantMessage(Static):
    """Renders assistant output as streaming Markdown.

    Call ``append_text()`` to incrementally add tokens.
    """

    DEFAULT_CSS = """
    AssistantMessage {
        width: 1fr;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    _content_text: str = ""

    def __init__(
        self,
        text: str = "",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._content_text = text
        self.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def compose(self):  # noqa: ANN201
        """Yield a single Markdown widget for the content."""
        yield Markdown(self._content_text, id="assistant-md")

    def append_text(self, chunk: str) -> None:
        """Append streaming text and re-render the Markdown."""
        self._content_text += chunk
        try:
            md = self.query_one("#assistant-md", Markdown)
            md.update(self._content_text)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Thought (agent thinking)
# ---------------------------------------------------------------------------

class ThoughtMessage(BaseMessage):
    """Dimmed italic text representing agent internal thinking."""

    DEFAULT_CSS = """
    ThoughtMessage {
        width: 1fr;
        padding: 0 1;
        margin: 0 0 1 0;
        color: #5C6370;
        text-style: italic;
    }
    """

    def __init__(
        self,
        text: str,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(text, name=name, id=id, classes=classes)


# ---------------------------------------------------------------------------
# Tool call
# ---------------------------------------------------------------------------

_STATUS_ICONS = {
    "pending": "\u23f3",    # hourglass
    "running": "\u25b6",    # play
    "success": "\u2705",    # check
    "error":   "\u274c",    # cross
}


class ToolCallMessage(BaseMessage):
    """Displays a tool call with name, status icon, and expandable details.

    Supports two construction patterns:
      - ``ToolCallMessage(tool_name)`` — standalone usage
      - ``ToolCallMessage(tool_id, title, kind, status)`` — ChatScreen usage
    """

    DEFAULT_CSS = """
    ToolCallMessage {
        width: 1fr;
        padding: 0 1;
        margin: 0 0 1 0;
        color: $text;
        background: $surface;
    }
    """

    tool_name: reactive[str] = reactive("")
    status: reactive[str] = reactive("pending")
    details: reactive[str] = reactive("")
    expanded: reactive[bool] = reactive(False)

    def __init__(
        self,
        tool_name: str,
        title: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        *,
        details: str = "",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        # Support both calling conventions:
        #   ToolCallMessage("read_file")
        #   ToolCallMessage("tool-abc123", "read_file", "tool", "pending")
        if title is not None:
            # Called from ChatScreen: (tool_id, title, kind, status)
            widget_id = f"tool-{tool_name}" if not (id or "").startswith("tool-") else id
            super().__init__(name=name, id=widget_id, classes=classes)
            self.tool_name = title
            self.status = status or "pending"
            self._kind = kind or "tool"
        else:
            super().__init__(name=name, id=id, classes=classes)
            self.tool_name = tool_name
            self._kind = "tool"
        self.details = details

    def update_status(self, status: str, details: str | None = None) -> None:
        """Update the tool call status and optionally replace the details."""
        self.status = status
        if details is not None:
            self.details = details

    def apply_progress(self, update: object) -> None:
        """Apply a ToolCallProgress ACP update."""
        new_status = getattr(update, "status", None)
        new_title = getattr(update, "title", None)
        if new_status:
            self.status = new_status
        if new_title:
            self.tool_name = new_title

    def on_click(self) -> None:
        """Toggle the expanded state on click."""
        self.expanded = not self.expanded

    def render(self) -> str:
        icon = _STATUS_ICONS.get(self.status, "\u2753")
        header = f"{icon} [bold]{self.tool_name}[/bold]"
        if self.expanded and self.details:
            return f"{header}\n{self.details}"
        return header


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class ErrorMessage(BaseMessage):
    """Red-styled error display."""

    DEFAULT_CSS = """
    ErrorMessage {
        width: 1fr;
        padding: 0 1;
        margin: 0 0 1 0;
        color: $error;
        background: $error 10%;
    }
    """

    def __init__(
        self,
        text: str,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(f"[bold red]Error:[/bold red] {text}", name=name, id=id, classes=classes)


# ---------------------------------------------------------------------------
# Plan entry (inline display)
# ---------------------------------------------------------------------------

_PLAN_STATUS_ICONS = {
    "completed": "\u2713",     # checkmark
    "in_progress": "\u2192",   # arrow
    "pending": "\u25cb",       # circle
}


class PlanEntryMessage(BaseMessage):
    """Inline display of a single plan/todo item with a status icon."""

    DEFAULT_CSS = """
    PlanEntryMessage {
        width: 1fr;
        padding: 0 1;
        margin: 0;
        color: #5C6370;
    }
    """

    def __init__(
        self,
        content: str,
        status: str = "pending",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        icon = _PLAN_STATUS_ICONS.get(status, "\u25cb")
        super().__init__(f"{icon} {content}", name=name, id=id, classes=classes)
