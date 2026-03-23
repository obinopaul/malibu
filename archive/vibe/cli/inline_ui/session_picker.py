# vibe/cli/inline_ui/session_picker.py
"""Session picker for inline mode using prompt_toolkit."""
from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.table import Table


async def pick_session(
    sessions: list[dict],
    latest_messages: dict[str, str | None],
    console: Console | None = None,
) -> str | None:
    """Show session list and return selected session ID."""
    console = console or Console(highlight=False)

    table = Table(title="Sessions", border_style="bright_black")
    table.add_column("#", style="cyan", width=3)
    table.add_column("Session", style="default")
    table.add_column("Time", style="bright_black")
    table.add_column("Message", style="default", max_width=60)

    for i, s in enumerate(sessions[:20], 1):
        sid = s["session_id"][:8]
        end_time = s.get("end_time", "")[:19] if s.get("end_time") else ""
        msg = latest_messages.get(s["session_id"], "") or ""
        if len(msg) > 57:
            msg = msg[:57] + "..."
        table.add_row(str(i), sid, end_time, msg)

    console.print(table)
    console.print("Enter number to resume, or 'q' to cancel:")

    session = PromptSession()
    choice = await session.prompt_async(HTML("<cyan>> </cyan>"))
    choice = choice.strip()

    if choice.lower() in ("q", "quit", ""):
        return None

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(sessions):
            return sessions[idx]["session_id"]
    except ValueError:
        pass

    return None
