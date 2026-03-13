"""Virtualized scrollable container for chat message widgets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from acp.schema import ToolCallProgress


class MessageList(VerticalScroll):
    """A scrollable container that holds message widgets.

    When ``auto_scroll`` is ``True`` (the default), the list
    automatically scrolls to the bottom whenever a new message is added.
    """

    DEFAULT_CSS = """
    MessageList {
        height: 1fr;
        padding: 0 1;
    }
    """

    auto_scroll: reactive[bool] = reactive(True)

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)

    async def add_message(self, widget: Widget) -> None:
        """Mount a message widget and optionally scroll to bottom."""
        await self.mount(widget)
        if self.auto_scroll:
            self.scroll_end(animate=False)

    def clear_messages(self) -> None:
        """Remove all child message widgets."""
        self.remove_children()

    # ── Convenience helpers used by ChatScreen ──────────────────

    def append_assistant_text(self, text: str) -> None:
        """Append text to the latest AssistantMessage or create a new one."""
        from malibu.tui.widgets.messages import AssistantMessage

        children = self.query("AssistantMessage")
        if children:
            last = children.last()
            last.append_text(text)
        else:
            msg = AssistantMessage(text)
            self.mount(msg)
        self.scroll_end(animate=False)

    def append_thought(self, text: str) -> None:
        """Append a dimmed thought message."""
        self.mount(Static(f"[dim italic](thinking: {text})[/]", classes="thought"))
        self.scroll_end(animate=False)

    def append_user_message(self, text: str) -> None:
        """Append a user message."""
        from malibu.tui.widgets.messages import UserMessage

        self.mount(UserMessage(text))
        self.scroll_end(animate=False)

    def add_tool_call(self, tool_id: str, title: str, kind: str, status: str) -> None:
        """Add a tool call status widget."""
        from malibu.tui.widgets.messages import ToolCallMessage

        widget = ToolCallMessage(tool_id, title, kind, status)
        self.mount(widget)
        self.scroll_end(animate=False)

    def update_tool_call(self, tool_id: str, update: ToolCallProgress) -> None:
        """Update an existing tool call widget's status."""
        from malibu.tui.widgets.messages import ToolCallMessage

        try:
            widget = self.query_one(f"#tool-{tool_id}", ToolCallMessage)
            widget.apply_progress(update)
        except Exception:
            title = getattr(update, "title", None) or "tool"
            self.add_tool_call(tool_id, title, "tool", getattr(update, "status", None) or "running")
        self.scroll_end(animate=False)
