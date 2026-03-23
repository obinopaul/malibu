"""Spinner implementations for the inline UI.

WaitingSpinner: Background thread spinner for "waiting for LLM" state.
  Uses raw stdout writes (carriage return) to avoid conflicting with Rich Live.
  Inspired by Aider's waiting.py.

StatusSpinner: Rich-based spinner for tool calls.
  Uses Rich Console.status() context manager.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Any

from rich.console import Console
from rich.text import Text


BRAILLE_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class WaitingSpinner:
    """Background thread spinner that writes directly to stdout.

    Shows a braille animation with status text. Starts invisible
    and becomes visible after `visible_after` seconds to avoid
    flashing on fast responses.
    """

    def __init__(
        self,
        text: str = "Generating",
        delay: float = 0.1,
        visible_after: float = 0.5,
    ) -> None:
        self.text = text
        self.delay = delay
        self.visible_after = visible_after
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_time: float = 0

    def start(self) -> None:
        self._start_time = time.time()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        # Clear the spinner line
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def _spin(self) -> None:
        frame_idx = 0
        while not self._stop_event.is_set():
            elapsed = time.time() - self._start_time
            if elapsed >= self.visible_after:
                frame = BRAILLE_FRAMES[frame_idx % len(BRAILLE_FRAMES)]
                elapsed_str = f"{int(elapsed)}s"
                line = f"\r{frame} {self.text}... ({elapsed_str})"
                sys.stdout.write(line)
                sys.stdout.flush()
                frame_idx += 1
            self._stop_event.wait(self.delay)


class StatusSpinner:
    """Rich-based status spinner for tool calls."""

    def __init__(self, **console_kwargs: Any) -> None:
        self.console = Console(highlight=False, **console_kwargs)
        self._status_text: str = ""

    def start(self, text: str) -> None:
        self._status_text = text
        self.console.print(Text(f"⠋ {text}", style="cyan"), end="")

    def stop(self, success: bool = True) -> None:
        icon = "✓" if success else "✕"
        style = "green" if success else "red"
        # Overwrite the spinner line
        self.console.print(f"\r{icon} {self._status_text}", style=style)
