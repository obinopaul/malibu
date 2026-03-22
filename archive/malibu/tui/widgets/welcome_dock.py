"""Pinned welcome dock shown at the top of the chat shell until activity begins."""

from __future__ import annotations

from pathlib import Path

import malibu
from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from textual.widgets import Static


_DOCK_BANNER = r"""
 __  ___      ___  _ __
/  |/  /___ _/ (_)/ /_  __  __
/ /|_/ / __ `/ / / __ \/ / / /
/ /  / / /_/ / / / /_/ / /_/ /
/_/  /_/\__,_/_/_/_.___/\__,_/
""".strip("\n")


class WelcomeDock(Static):
    """Compact welcome surface that mirrors the launch screen in the shell."""

    DEFAULT_CSS = """
    WelcomeDock {
        margin: 1 1 0 1;
        height: auto;
    }
    WelcomeDock.-hidden {
        display: none;
    }
    """

    def __init__(self, *, cwd: str = ".") -> None:
        super().__init__(id="welcome-dock")
        self._cwd = str(Path(cwd).resolve())
        self._session_title = "New Session"
        self._mode_name = "accept_edits"
        self._model_id = ""
        self._ready = False
        self._refresh_content()

    def set_cwd(self, cwd: str) -> None:
        self._cwd = str(Path(cwd).resolve())
        self._refresh_content()

    def set_session_title(self, title: str) -> None:
        self._session_title = title
        self._refresh_content()

    def set_mode(self, mode: str) -> None:
        self._mode_name = mode
        self._refresh_content()

    def set_model(self, model_id: str) -> None:
        self._model_id = model_id
        self._refresh_content()

    def set_ready(self, ready: bool) -> None:
        self._ready = ready
        self._refresh_content()

    def dismiss(self) -> None:
        self.add_class("-hidden")

    def reveal(self) -> None:
        self.remove_class("-hidden")

    def refresh_theme(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        self.update(
            build_welcome_renderable(
                cwd=self._cwd,
                session_title=self._session_title,
                mode_name=self._mode_name,
                model_id=self._model_id,
                ready=self._ready,
                theme=getattr(self.app, "current_theme", None) if getattr(self, "app", None) else None,
            )
        )


def build_welcome_renderable(
    *,
    cwd: str,
    session_title: str,
    mode_name: str,
    model_id: str,
    ready: bool,
    theme: object | None,
) -> Panel:
    """Build the shared welcome renderable used in the dock and scroll history."""

    accent = getattr(theme, "accent", None) or getattr(theme, "primary", None) or "#D7A77A"
    foreground = getattr(theme, "foreground", None) or "#F3EBDD"
    muted = getattr(theme, "variables", {}).get("foreground-muted", "#AA9988") if theme else "#AA9988"
    success = getattr(theme, "success", None) or "#879A63"

    cwd_name = cwd
    status_text = "Shell ready" if ready else "Starting local session..."
    status_style = success if ready else accent

    left = Group(
        Text("Welcome to Malibu", style=f"bold {foreground}"),
        Text(_DOCK_BANNER, style=accent),
        Text(f"v{malibu.__version__}", style=muted),
        Text(cwd_name, style=muted),
    )
    right_lines = [
        Text("Quick Start", style=f"bold {accent}"),
        Text("Use / to browse commands, models, sessions, and modes.", style=foreground),
        Text("Shift+Enter inserts a newline. Ctrl+L clears the chat.", style=foreground),
        Text("The banner stays in history as the conversation grows.", style=muted),
        Text(""),
        Text(f"session  {session_title}", style=muted),
        Text(f"mode     {mode_name}", style=foreground),
        Text(f"model    {model_id or 'waiting for bootstrap'}", style=muted),
        Text(status_text, style=status_style),
    ]
    return Panel(
        Columns([left, Group(*right_lines)], equal=True, expand=True),
        border_style=accent,
        padding=(0, 1),
        title="Malibu Shell",
    )
