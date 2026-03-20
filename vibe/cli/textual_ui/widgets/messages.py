from __future__ import annotations

import asyncio
import time
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static
from textual.widgets._markdown import MarkdownStream

from vibe.cli.textual_ui.ansi_markdown import AnsiMarkdown as Markdown
from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic
from vibe.cli.textual_ui.widgets.spinner import SpinnerMixin, SpinnerType


class NonSelectableStatic(NoMarkupStatic):
    @property
    def text_selection(self) -> None:
        return None

    @text_selection.setter
    def text_selection(self, value: Any) -> None:
        pass

    def get_selection(self, selection: Any) -> None:
        return None


class ExpandingBorder(NonSelectableStatic):
    def render(self) -> str:
        height = self.size.height
        return "\n".join(["⎢"] * (height - 1) + ["⎣"])

    def on_resize(self) -> None:
        self.refresh()


class UserMessage(Static):
    def __init__(self, content: str, pending: bool = False) -> None:
        super().__init__()
        self.add_class("user-message")
        self._content = content
        self._pending = pending

    def compose(self) -> ComposeResult:
        with Horizontal(classes="user-message-container"):
            yield NoMarkupStatic(self._content, classes="user-message-content")
            if self._pending:
                self.add_class("pending")

    async def set_pending(self, pending: bool) -> None:
        if pending == self._pending:
            return

        self._pending = pending

        if pending:
            self.add_class("pending")
            return

        self.remove_class("pending")


class StreamingMessageBase(Static):
    """Base class for messages that stream content incrementally.

    Two performance mechanisms work together to prevent terminal freezes:

    1. **Adaptive render throttle** (from Aider's mdstream.py):
       Measures how long each MarkdownStream.write() takes, then sets the
       minimum interval to 10x the render cost. Fast terminals get ~20 FPS;
       slow terminals auto-degrade to 2 FPS instead of freezing.

    2. **Write suspension** (from Textual internals analysis):
       When the user scrolls away from the bottom during streaming, writes
       are suspended — tokens accumulate in a buffer but NO MarkdownStream
       writes happen. This is critical because Markdown.append() mounts new
       child widgets which set _layout_required=True, causing scroll events
       to bypass Textual's fast reflow path and trigger expensive full
       compositor reflows. Suspending writes during scroll eliminates this
       collision entirely.
    """

    _MIN_INTERVAL = 0.05   # 20 FPS floor — never render faster than this
    _MAX_INTERVAL = 0.5    # 2 FPS ceiling — never render slower than this
    _RENDER_COST_MULTIPLIER = 10  # interval = render_time * this

    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content
        self._markdown: Markdown | None = None
        self._stream: MarkdownStream | None = None
        self._content_initialized = False
        self._pending_content = ""
        self._last_write_time = 0.0
        self._write_interval = self._MIN_INTERVAL
        self._flush_timer: asyncio.TimerHandle | None = None
        self._writes_suspended = False

    def _get_markdown(self) -> Markdown:
        if self._markdown is None:
            raise RuntimeError(
                "Markdown widget not initialized. compose() must be called first."
            )
        return self._markdown

    def _ensure_stream(self) -> MarkdownStream:
        if self._stream is None:
            self._stream = Markdown.get_stream(self._get_markdown())
        return self._stream

    def suspend_writes(self) -> None:
        """Suspend MarkdownStream writes. Tokens keep accumulating in the
        buffer but nothing is rendered. Call this when the user scrolls away
        from the bottom to prevent widget mounts from colliding with scroll
        layout passes."""
        self._writes_suspended = True
        # Cancel any pending flush timer — we don't want it firing while
        # suspended since it would try to write
        if self._flush_timer is not None:
            self._flush_timer.cancel()
            self._flush_timer = None

    async def resume_writes(self) -> None:
        """Resume writes and flush all buffered content in one batch.
        Call this when the user scrolls back to the bottom."""
        if not self._writes_suspended:
            return
        self._writes_suspended = False
        # Flush everything that accumulated while suspended — one big write
        # is much cheaper than many small ones
        await self._flush_pending()

    async def append_content(self, content: str) -> None:
        if not content:
            return

        self._content += content
        self._pending_content += content

        # When suspended, just accumulate — don't schedule any writes.
        # The content is safe in _pending_content and _content.
        if self._writes_suspended:
            return

        now = time.monotonic()
        elapsed = now - self._last_write_time

        if elapsed >= self._write_interval:
            await self._flush_pending()
        elif self._flush_timer is None:
            delay = self._write_interval - elapsed
            loop = asyncio.get_running_loop()
            self._flush_timer = loop.call_later(
                delay, lambda: asyncio.ensure_future(self._flush_pending())
            )

    async def _flush_pending(self) -> None:
        if self._flush_timer is not None:
            self._flush_timer.cancel()
            self._flush_timer = None
        if not self._pending_content:
            return
        # Don't flush while suspended — content stays in buffer
        if self._writes_suspended:
            return

        text = self._pending_content
        self._pending_content = ""

        if self._should_write_content():
            stream = self._ensure_stream()
            t0 = time.monotonic()
            await stream.write(text)
            render_time = time.monotonic() - t0

            # Adaptive throttle: back off proportionally to render cost
            self._write_interval = min(
                max(render_time * self._RENDER_COST_MULTIPLIER, self._MIN_INTERVAL),
                self._MAX_INTERVAL,
            )

        self._last_write_time = time.monotonic()

    async def write_initial_content(self) -> None:
        if self._content_initialized:
            return
        if self._content and self._should_write_content():
            stream = self._ensure_stream()
            await stream.write(self._content)

    async def stop_stream(self) -> None:
        # Force-resume so all buffered content is flushed before stopping
        self._writes_suspended = False
        await self._flush_pending()
        if self._stream is None:
            return
        await self._stream.stop()
        self._stream = None

    def _should_write_content(self) -> bool:
        return True

    def is_stripped_content_empty(self) -> bool:
        return self._content.strip() == ""

    @property
    def content(self) -> str:
        return self._content


class AssistantMessage(StreamingMessageBase):
    def __init__(self, content: str) -> None:
        super().__init__(content)
        self.add_class("assistant-message")

    def compose(self) -> ComposeResult:
        if self._content:
            self._content_initialized = True
        markdown = Markdown(self._content)
        self._markdown = markdown
        yield markdown


class ReasoningMessage(SpinnerMixin, StreamingMessageBase):
    SPINNER_TYPE = SpinnerType.PULSE
    SPINNING_TEXT = "Thinking"
    COMPLETED_TEXT = "Thought"

    def __init__(
        self, content: str, collapsed: bool = True, *, completed: bool = False
    ) -> None:
        super().__init__(content)
        self.add_class("reasoning-message")
        self.collapsed = collapsed
        self.completed = completed
        self._indicator_widget: Static | None = None
        self._triangle_widget: Static | None = None
        self.init_spinner()
        if completed:
            self._is_spinning = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="reasoning-message-wrapper"):
            with Horizontal(classes="reasoning-message-header"):
                self._indicator_widget = NonSelectableStatic(
                    "✓" if self.completed else self._spinner.current_frame(),
                    classes="reasoning-indicator",
                )
                if self.completed:
                    self._indicator_widget.add_class("success")
                yield self._indicator_widget
                self._status_text_widget = NoMarkupStatic(
                    self.COMPLETED_TEXT if self.completed else self.SPINNING_TEXT,
                    classes="reasoning-collapsed-text",
                )
                yield self._status_text_widget
                self._triangle_widget = NonSelectableStatic(
                    "▶" if self.collapsed else "▼", classes="reasoning-triangle"
                )
                yield self._triangle_widget
            markdown = Markdown("", classes="reasoning-message-content")
            markdown.display = not self.collapsed
            self._markdown = markdown
            yield markdown

    def on_mount(self) -> None:
        if self.completed:
            return
        self.start_spinner_timer()

    def on_resize(self) -> None:
        self.refresh_spinner()

    async def on_click(self) -> None:
        await self._toggle_collapsed()

    async def _toggle_collapsed(self) -> None:
        await self.set_collapsed(not self.collapsed)

    def _should_write_content(self) -> bool:
        return not self.collapsed

    async def set_collapsed(self, collapsed: bool) -> None:
        if self.collapsed == collapsed:
            return

        self.collapsed = collapsed
        if self._triangle_widget:
            self._triangle_widget.update("▶" if collapsed else "▼")
        if self._markdown:
            self._markdown.display = not collapsed
            if not collapsed and self._content:
                if self._stream is not None:
                    await self._stream.stop()
                    self._stream = None
                await self._markdown.update("")
                stream = self._ensure_stream()
                await stream.write(self._content)


class UserCommandMessage(Static):
    def __init__(self, content: str) -> None:
        super().__init__()
        self.add_class("user-command-message")
        self._content = content

    def compose(self) -> ComposeResult:
        with Horizontal(classes="user-command-container"):
            yield ExpandingBorder(classes="user-command-border")
            with Vertical(classes="user-command-content"):
                yield Markdown(self._content)


class WhatsNewMessage(Static):
    def __init__(self, content: str) -> None:
        super().__init__()
        self.add_class("whats-new-message")
        self._content = content

    def compose(self) -> ComposeResult:
        yield Markdown(self._content)


class InterruptMessage(Static):
    def __init__(self) -> None:
        super().__init__()
        self.add_class("interrupt-message")

    def compose(self) -> ComposeResult:
        with Horizontal(classes="interrupt-container"):
            yield ExpandingBorder(classes="interrupt-border")
            yield NoMarkupStatic(
                "Interrupted · What should Malibu do instead?",
                classes="interrupt-content",
            )


class BashOutputMessage(Static):
    def __init__(self, command: str, cwd: str, output: str, exit_code: int) -> None:
        super().__init__()
        self.add_class("bash-output-message")
        self._command = command
        self._cwd = cwd
        self._output = output.rstrip("\n")
        self._exit_code = exit_code

    def compose(self) -> ComposeResult:
        status_class = "bash-success" if self._exit_code == 0 else "bash-error"
        self.add_class(status_class)
        with Horizontal(classes="bash-command-line"):
            yield NonSelectableStatic("$ ", classes=f"bash-prompt {status_class}")
            yield NoMarkupStatic(self._command, classes="bash-command")
        with Horizontal(classes="bash-output-container"):
            yield ExpandingBorder(classes="bash-output-border")
            yield NoMarkupStatic(self._output, classes="bash-output")


class ErrorMessage(Static):
    def __init__(self, error: str, collapsed: bool = False) -> None:
        super().__init__()
        self.add_class("error-message")
        self._error = error
        self.collapsed = collapsed
        self._content_widget: Static | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="error-container"):
            yield ExpandingBorder(classes="error-border")
            self._content_widget = NoMarkupStatic(
                f"Error: {self._error}", classes="error-content"
            )
            yield self._content_widget

    def set_collapsed(self, collapsed: bool) -> None:
        pass


class WarningMessage(Static):
    def __init__(self, message: str, show_border: bool = True) -> None:
        super().__init__()
        self.add_class("warning-message")
        self._message = message
        self._show_border = show_border

    def compose(self) -> ComposeResult:
        with Horizontal(classes="warning-container"):
            if self._show_border:
                yield ExpandingBorder(classes="warning-border")
            yield NoMarkupStatic(self._message, classes="warning-content")
