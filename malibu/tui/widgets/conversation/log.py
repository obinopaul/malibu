"""Conversation log widget for the Malibu TUI shell."""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll

from malibu.tui.widgets.conversation.blocks import (
    AssistantMessageBlock,
    InlineDecisionBlock,
    SystemMessageBlock,
    ThoughtMessageBlock,
    ToolCallBlock,
    ToolGroupBlock,
    UserMessageBlock,
    WelcomeMessageBlock,
)


class ConversationLog(VerticalScroll):
    """Scrollable conversation surface with tool and prompt helpers."""

    DEFAULT_CSS = """
    ConversationLog {
        width: 1fr;
        height: 1fr;
        padding: 1 2 0 1;
        background: transparent;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="conversation-log")
        self.auto_follow = True
        self._assistant_block: AssistantMessageBlock | None = None
        self._tool_blocks: dict[str, ToolCallBlock] = {}
        self._inline_prompt: Any | None = None
        self._welcome_block: WelcomeMessageBlock | None = None

    def set_welcome_message(
        self,
        *,
        cwd: str,
        session_title: str,
        mode_name: str,
        model_id: str,
        ready: bool,
    ) -> None:
        if self._welcome_block is None or not self._welcome_block.parent:
            self._welcome_block = WelcomeMessageBlock(
                cwd=cwd,
                session_title=session_title,
                mode_name=mode_name,
                model_id=model_id,
                ready=ready,
            )
            self.mount(self._welcome_block)

    def add_user_message(self, text: str) -> None:
        self._assistant_block = None
        self.mount(UserMessageBlock(text))
        self.scroll_latest()

    def add_assistant_message(self, text: str) -> None:
        if self._assistant_block is None or not self._assistant_block.parent:
            self._assistant_block = AssistantMessageBlock(text)
            self.mount(self._assistant_block)
        else:
            self._assistant_block.append_text(text)
        self.scroll_latest()

    def add_system_message(self, text: str, *, title: str = "System", border_style: str = "#475569") -> None:
        self._assistant_block = None
        self.mount(SystemMessageBlock(text, title=title, border_style=border_style))
        self.scroll_latest()

    def add_thought(self, text: str) -> None:
        self._assistant_block = None
        self.mount(ThoughtMessageBlock(text))
        self.scroll_latest()

    def start_tool_call(
        self,
        tool_call_id: str,
        title: str,
        *,
        kind: str = "tool",
        status: str = "pending",
        raw_input: Any = None,
    ) -> ToolCallBlock:
        self._assistant_block = None
        block = self._tool_blocks.get(tool_call_id)
        if block is None or not block.parent:
            block = ToolCallBlock(
                tool_call_id=tool_call_id,
                title=title,
                kind=kind,
                status=status,
                raw_input=raw_input,
            )
            self._tool_blocks[tool_call_id] = block
            self.mount(block)
        else:
            block.set_title(title)
            block.set_status(status)
            block.set_input(raw_input)
        self.scroll_latest()
        return block

    def update_tool_call(
        self,
        tool_call_id: str,
        *,
        title: str | None = None,
        status: str | None = None,
        raw_input: Any = None,
        output_text: str | None = None,
        truncated: bool = False,
    ) -> ToolCallBlock:
        block = self._tool_blocks.get(tool_call_id)
        if block is None:
            block = self.start_tool_call(tool_call_id, title or "Tool", status=status or "pending", raw_input=raw_input)
        if title:
            block.set_title(title)
        if status:
            block.set_status(status)
        if raw_input is not None:
            block.set_input(raw_input)
        if output_text is not None:
            block.set_output(output_text, truncated=truncated)
        self.scroll_latest()
        return block

    def add_tool_group(self, title: str, items: list[str]) -> None:
        self._assistant_block = None
        self.mount(ToolGroupBlock(title, items))
        self.scroll_latest()

    def render_inline_prompt(self, block: InlineDecisionBlock) -> None:
        self.clear_inline_prompt()
        self._inline_prompt = block
        self.mount(block)
        self.scroll_latest()

    def clear_inline_prompt(self) -> None:
        if self._inline_prompt is not None and getattr(self._inline_prompt, "parent", None):
            self._inline_prompt.remove()
        self._inline_prompt = None

    def clear_log(self) -> None:
        self.remove_children()
        self._tool_blocks.clear()
        self._assistant_block = None
        self._inline_prompt = None
        self._welcome_block = None

    def refresh_theme(self) -> None:
        for child in self.children:
            if hasattr(child, "refresh_theme"):
                child.refresh_theme()  # type: ignore[call-arg]

    def scroll_latest(self) -> None:
        if self.auto_follow:
            self.scroll_end(animate=False)
