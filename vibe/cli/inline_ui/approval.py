# vibe/cli/inline_ui/approval.py
"""Tool approval prompts for the inline UI.

Replaces the Textual ApprovalApp modal with prompt_toolkit prompts.
Supports: Yes / Always for this tool / No (with feedback)
"""
from __future__ import annotations

from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from vibe.core.types import ApprovalResponse


def format_approval_prompt(tool_name: str, args: Any) -> str:
    """Format tool call info for display."""
    lines = [f"Tool: {tool_name}"]
    if hasattr(args, "model_dump"):
        for k, v in args.model_dump().items():
            val_str = str(v)
            if len(val_str) > 200:
                val_str = val_str[:200] + "..."
            lines.append(f"  {k}: {val_str}")
    elif isinstance(args, dict):
        for k, v in args.items():
            val_str = str(v)
            if len(val_str) > 200:
                val_str = val_str[:200] + "..."
            lines.append(f"  {k}: {val_str}")
    return "\n".join(lines)


async def prompt_approval(
    tool_name: str,
    tool_args: Any,
    console: Console | None = None,
) -> tuple[ApprovalResponse, str | None]:
    """Show approval prompt and return (response, feedback)."""
    console = console or Console(highlight=False)

    info = format_approval_prompt(tool_name, tool_args)
    console.print()
    console.print(
        Panel(
            Text(info),
            title="[yellow]Approve tool call?[/yellow]",
            title_align="left",
            border_style="yellow",
            padding=(0, 1),
        )
    )
    console.print(
        Text("  (y)es  (a)lways  (n)o", style="bright_black")
    )

    session: PromptSession[str] = PromptSession()
    answer = await session.prompt_async(HTML("<yellow>? </yellow>"))
    answer = answer.strip().lower()

    if answer in ("y", "yes", ""):
        return (ApprovalResponse.YES, None)
    elif answer in ("a", "always"):
        return (ApprovalResponse.YES, "__always__")
    else:
        feedback = answer if answer not in ("n", "no") else None
        return (ApprovalResponse.NO, feedback)
