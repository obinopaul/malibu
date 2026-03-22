"""Routes agent loop events to the inline renderer."""
from __future__ import annotations

from typing import Any

from vibe.cli.inline_ui.markdown_stream import MarkdownStream
from vibe.cli.inline_ui.renderer import OutputRenderer
from vibe.cli.inline_ui.tool_display import ToolDisplay
from vibe.core.types import (
    AssistantEvent,
    CompactEndEvent,
    CompactStartEvent,
    ReasoningEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolStreamEvent,
)


class InlineEventHandler:
    """Handles agent events and renders them inline."""

    def __init__(
        self,
        renderer: OutputRenderer,
        tool_display: ToolDisplay,
        tools_collapsed: bool = True,
    ) -> None:
        self.renderer = renderer
        self.tool_display = tool_display
        self.tools_collapsed = tools_collapsed

        self._current_stream: MarkdownStream | None = None
        self._accumulated_text: str = ""
        self._current_reasoning: str = ""
        self._current_tool_name: str | None = None

    async def handle_event(self, event: Any) -> None:
        """Dispatch an agent event to the appropriate handler."""
        if isinstance(event, AssistantEvent) and event.content:
            self._handle_assistant_chunk(event.content)
        elif isinstance(event, ReasoningEvent) and event.content:
            self._handle_reasoning_chunk(event.content)
        elif isinstance(event, ToolCallEvent):
            self._handle_tool_call(event)
        elif isinstance(event, ToolStreamEvent) and event.message:
            pass  # Tool stream text — could show if desired
        elif isinstance(event, ToolResultEvent):
            self._handle_tool_result(event)
        elif isinstance(event, CompactStartEvent):
            from rich.text import Text
            self.renderer.console.print(
                Text(f"Compacting context ({event.current_context_tokens:,} tokens)...",
                     style="bright_black")
            )
        elif isinstance(event, CompactEndEvent):
            from rich.text import Text
            saved = event.old_context_tokens - event.new_context_tokens
            self.renderer.console.print(
                Text(f"Compacted: {event.old_context_tokens:,} → {event.new_context_tokens:,} "
                     f"tokens (saved {saved:,})", style="green")
            )

    def _handle_assistant_chunk(self, content: str) -> None:
        if self._current_stream is None:
            self._current_stream = MarkdownStream()
            self._accumulated_text = ""

        self._accumulated_text += content
        self._current_stream.update(self._accumulated_text, final=False)

    def _handle_reasoning_chunk(self, content: str) -> None:
        self._current_reasoning += content

    def _handle_tool_call(self, event: ToolCallEvent) -> None:
        self._finalize_stream()
        self._current_tool_name = event.tool_name
        args = event.args
        self.tool_display.show_tool_call(
            event.tool_name,
            args,
            collapsed=self.tools_collapsed,
        )

    def _handle_tool_result(self, event: ToolResultEvent) -> None:
        tool_name = self._current_tool_name or event.tool_name
        is_error = event.error is not None

        self.tool_display.show_tool_complete(tool_name, success=not is_error)

        if event.error:
            self.tool_display.show_tool_result(
                tool_name,
                event.error,
                is_error=True,
                collapsed=False,
            )
        elif event.result is not None:
            result_text = str(event.result)
            if hasattr(event.result, "model_dump"):
                dumped = event.result.model_dump()
                result_text = str(
                    dumped.get("content")
                    or dumped.get("output")
                    or dumped.get("result")
                    or dumped
                )

            if result_text.startswith("---") or result_text.startswith("diff"):
                self.tool_display.show_diff(result_text)
            else:
                self.tool_display.show_tool_result(
                    tool_name,
                    result_text,
                    is_error=False,
                    collapsed=self.tools_collapsed,
                )
        elif event.skipped:
            from rich.text import Text
            self.renderer.console.print(
                Text(f"  Skipped: {event.skip_reason or 'no reason'}", style="bright_black")
            )
        self._current_tool_name = None

    def _finalize_stream(self) -> None:
        if self._current_stream is not None and self._accumulated_text:
            self._current_stream.update(self._accumulated_text, final=True)
            self._current_stream = None
            self._accumulated_text = ""

    def finalize(self) -> None:
        self._finalize_stream()
        if self._current_reasoning:
            self.renderer.console.print()
            self._current_reasoning = ""
