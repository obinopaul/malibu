# vibe/cli/inline_ui/renderer.py
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

# Malibu orange from the existing Textual CSS
MALIBU_ORANGE = "#FF8205"

THEME = Theme({
    "user": f"bold {MALIBU_ORANGE}",
    "assistant": "default",
    "tool.name": "bold cyan",
    "tool.arg": "dim",
    "error": "bold red",
    "warning": "yellow",
    "success": "bold green",
    "info": "dim",
    "interrupt": "yellow",
    "command": "default",
    "border": "bright_black",
    "spinner": "cyan",
})


class OutputRenderer:
    """Renders all output to the terminal via Rich Console.

    Every method here prints directly to the primary terminal buffer.
    The terminal's native scrollbar handles scrolling — no virtual DOM,
    no layout engine, no compositor overhead.
    """

    def __init__(self, **console_kwargs: Any) -> None:
        defaults: dict[str, Any] = {"highlight": False, "theme": THEME}
        defaults.update(console_kwargs)
        self.console = Console(**defaults)

    def user_message(self, content: str) -> None:
        """Print a user message with left border."""
        self.console.print()
        self.console.print(
            Text(content, style="user"),
            style="user",
            highlight=False,
        )

    def assistant_markdown(self, content: str) -> None:
        """Print finalized assistant markdown (non-streaming)."""
        self.console.print()
        self.console.print(Markdown(content))

    def error(self, message: str) -> None:
        self.console.print(Text(f"Error: {message}", style="error"))

    def warning(self, message: str) -> None:
        self.console.print(Text(message, style="warning"))

    def interrupt(self) -> None:
        self.console.print(
            Text("Interrupted - What should Malibu do instead?", style="interrupt")
        )

    def command_message(self, content: str) -> None:
        """Print system/command feedback (e.g. 'Configuration reloaded.')"""
        self.console.print(Markdown(content))

    def bash_output(
        self, command: str, output: str, exit_code: int
    ) -> None:
        """Print bash command + output."""
        prompt_style = "success" if exit_code == 0 else "error"
        self.console.print(Text(f"$ {command}", style=prompt_style))
        if output.strip():
            self.console.print(
                Panel(
                    Text(output.rstrip("\n")),
                    border_style="border",
                    padding=(0, 1),
                )
            )

    def status_line(self, text: str) -> None:
        """Print a dim status line."""
        self.console.print(Text(text, style="info"))

    def blank_line(self) -> None:
        self.console.print()
