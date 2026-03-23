"""Tool call and result rendering for the inline UI."""
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.theme import Theme


class ToolDisplay:
    """Renders tool calls and results to terminal."""

    TRUNCATE_LINES = 30
    TRUNCATE_RESULT_CHARS = 3000

    def __init__(self, **console_kwargs: Any) -> None:
        self.console = Console(highlight=False, **console_kwargs)

    def show_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any] | Any,
        collapsed: bool = True,
    ) -> None:
        name_text = Text(f"⠋ {tool_name}", style="cyan")
        self.console.print(name_text)

        if not collapsed and args:
            arg_dict = args if isinstance(args, dict) else (
                args.model_dump() if hasattr(args, "model_dump") else {}
            )
            for k, v in arg_dict.items():
                val_str = str(v)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "..."
                self.console.print(
                    Text(f"  {k}: {val_str}", style="bright_black")
                )

    def show_tool_complete(
        self, tool_name: str, success: bool = True
    ) -> None:
        icon = "✓" if success else "✕"
        style = "green" if success else "red"
        self.console.print(Text(f"{icon} {tool_name}", style=style))

    def show_tool_result(
        self,
        tool_name: str,
        result_text: str,
        is_error: bool = False,
        collapsed: bool = True,
    ) -> None:
        if collapsed and not is_error:
            return

        style = "red" if is_error else "bright_black"
        lines = result_text.split("\n")
        if len(lines) > self.TRUNCATE_LINES:
            truncated = "\n".join(lines[: self.TRUNCATE_LINES])
            truncated += f"\n... ({len(lines) - self.TRUNCATE_LINES} more lines)"
        elif len(result_text) > self.TRUNCATE_RESULT_CHARS:
            truncated = result_text[: self.TRUNCATE_RESULT_CHARS] + "..."
        else:
            truncated = result_text

        self.console.print(
            Panel(
                Text(truncated),
                border_style=style,
                padding=(0, 1),
            )
        )

    def show_diff(self, diff_text: str) -> None:
        self.console.print(
            Syntax(diff_text, "diff", theme="ansi_dark", padding=0)
        )

    def show_bash_output(
        self, command: str, cwd: str, output: str, exit_code: int
    ) -> None:
        prompt_style = "green" if exit_code == 0 else "red"
        self.console.print(Text(f"$ {command}", style=prompt_style))
        if output.strip():
            self.console.print(
                Panel(
                    Text(output.rstrip("\n")),
                    border_style="bright_black",
                    padding=(0, 1),
                )
            )
