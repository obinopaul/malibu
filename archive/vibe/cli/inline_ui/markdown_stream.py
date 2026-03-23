"""Streaming markdown renderer using Aider's stable/unstable line split.

Architecture:
- Re-renders the full accumulated markdown on each update
- Splits output into "stable" lines (flushed to permanent scrollback) and
  "unstable" lines (kept in Rich Live region, repainted in-place)
- Adaptive throttle: min_delay = clamp(render_time * 10, 1/20, 2)
- On final=True: flushes everything, stops Live, all content is in scrollback
"""
from __future__ import annotations

import io
import time
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text


class MarkdownStream:
    """Streams markdown to the terminal with adaptive throttle."""

    live: Live | None = None
    when: float = 0
    min_delay: float = 1.0 / 20  # 20 fps initial target
    live_window: int = 6          # unstable tail lines kept in Live region

    def __init__(self, **console_kwargs: Any) -> None:
        self.printed: list[str] = []
        # Extract special kwargs before passing remaining ones to Console
        self._file = console_kwargs.pop("file", None)
        self._force_terminal = console_kwargs.pop("force_terminal", False)
        self._console_kwargs = console_kwargs
        self.live = None
        self._live_started = False

    def _make_console(self) -> Console:
        kwargs: dict[str, Any] = {"highlight": False}
        if self._file is not None:
            kwargs["file"] = self._file
        if self._force_terminal:
            kwargs["force_terminal"] = True
        kwargs.update(self._console_kwargs)
        return Console(**kwargs)

    def _render_markdown_to_lines(self, text: str) -> list[str]:
        string_io = io.StringIO()
        console = Console(file=string_io, force_terminal=True)
        markdown = Markdown(text)
        console.print(markdown)
        output = string_io.getvalue()
        return output.splitlines(keepends=True)

    def __del__(self) -> None:
        if self.live:
            try:
                self.live.stop()
            except Exception:
                pass

    def update(self, text: str, final: bool = False) -> None:
        # Lazy init Live on first call
        if not self._live_started:
            console = self._make_console()
            self.live = Live(
                Text(""),
                console=console,
                refresh_per_second=1.0 / self.min_delay,
            )
            self.live.start()
            self._live_started = True

        now = time.time()
        if not final and now - self.when < self.min_delay:
            return  # throttle — skip this update
        self.when = now

        # Adaptive throttle: measure render cost
        start = time.time()
        lines = self._render_markdown_to_lines(text)
        render_time = time.time() - start
        self.min_delay = min(max(render_time * 10, 1.0 / 20), 2)

        num_lines = len(lines)

        # Stable/unstable split
        if not final:
            num_lines -= self.live_window

        if final or num_lines > 0:
            num_printed = len(self.printed)
            show_count = num_lines - num_printed
            if show_count <= 0 and not final:
                return

            if show_count > 0:
                # Flush stable lines above the Live region
                show = lines[num_printed:num_lines]
                show_text = "".join(show)
                show_rich = Text.from_ansi(show_text)
                assert self.live is not None
                self.live.console.print(show_rich)
                self.printed = lines[:num_lines]

        if final:
            # Flush the remaining (unstable) lines and stop
            num_printed = len(self.printed)
            if num_printed < len(lines):
                rest = lines[num_printed:]
                rest_text = "".join(rest)
                rest_rich = Text.from_ansi(rest_text)
                assert self.live is not None
                self.live.console.print(rest_rich)

            assert self.live is not None
            self.live.update(Text(""))
            self.live.stop()
            self.live = None
            self._live_started = False
            return

        # Update the unstable tail in the Live region
        rest = lines[num_lines:]
        rest_text = "".join(rest)
        rest_rich = Text.from_ansi(rest_text)
        assert self.live is not None
        self.live.update(rest_rich)
