# vibe/cli/inline_ui/status.py
"""Status display for the inline UI.

Shows token usage, cost, elapsed time as a single-line status.
"""
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.text import Text


def print_status(
    context_tokens: int = 0,
    max_tokens: int = 0,
    cost: float = 0.0,
    **console_kwargs: Any,
) -> None:
    """Print a status summary line."""
    console = Console(highlight=False, **console_kwargs)
    parts: list[str] = []

    if max_tokens > 0:
        pct = int(context_tokens / max_tokens * 100)
        parts.append(f"Context: {pct}% of {max_tokens // 1000}k")

    if cost > 0:
        parts.append(f"Cost: ${cost:.4f}")

    if parts:
        console.print(Text(" | ".join(parts), style="bright_black"))
