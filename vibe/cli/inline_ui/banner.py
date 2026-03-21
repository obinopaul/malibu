"""Static banner for the inline UI.

Prints the PetitChat braille art + version/model info once at startup.
No animation — just a single frame rendered to permanent scrollback.
"""
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.text import Text

MALIBU_ORANGE = "#FF8205"


def _build_braille_art() -> str:
    """Render the initial PetitChat frame as braille characters."""
    try:
        from vibe.cli.textual_ui.widgets.braille_renderer import render_braille
        from vibe.cli.textual_ui.widgets.banner.petit_chat import (
            STARTING_DOTS,
            WIDTH,
            HEIGHT,
        )

        dots = {1j * y + x for y, row in enumerate(STARTING_DOTS) for x in row}
        return render_braille(dots, WIDTH, HEIGHT)
    except Exception:
        # Fallback ASCII art if textual imports fail
        return (
            "  /\\_/\\  \n"
            " ( o.o ) \n"
            "  > ^ <  \n"
        )


def print_banner(
    model_name: str = "",
    version: str = "",
    agent_name: str = "malibu",
    **console_kwargs: Any,
) -> None:
    """Print the Malibu banner to the terminal."""
    console = Console(highlight=False, **console_kwargs)

    art = _build_braille_art()
    art_lines = art.split("\n")

    info_lines = [
        Text(""),
        Text("Malibu", style=f"bold {MALIBU_ORANGE}"),
        Text(f"v{version}", style="bright_black") if version else Text(""),
        Text(f"Model: {model_name}", style="cyan") if model_name else Text(""),
        Text(f"Agent: {agent_name}", style="default") if agent_name else Text(""),
        Text(""),
    ]

    # Print art lines with info alongside
    for i, art_line in enumerate(art_lines):
        line = Text(art_line + "  ")
        if i < len(info_lines):
            line.append_text(info_lines[i])
        console.print(line)

    console.print()
