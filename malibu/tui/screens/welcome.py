"""WelcomeScreen — splash / landing screen for the Malibu TUI.

Displays an ASCII art banner, version information, and quick-start hints.
Auto-transitions to ``ChatScreen`` after a brief delay or on any keypress.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

import malibu

_BANNER = r"""
    __  ___      ___  _ __
   /  |/  /___ _/ (_)/ /_  __  __
  / /|_/ / __ `/ / / __ \/ / / /
 / /  / / /_/ / / / /_/ / /_/ /
/_/  /_/\__,_/_/_/_.___/\__,_/
"""

_HINTS = """\
[bold]Quick start[/bold]
  Just start typing to chat with the agent.
  [dim]/help[/dim]  — list available commands
  [dim]/mode[/dim]  — switch agent mode
  [dim]ctrl+p[/dim] — toggle plan panel
  [dim]ctrl+l[/dim] — clear conversation

Press [bold]any key[/bold] to continue...
"""


class WelcomeScreen(Screen):
    """Splash screen shown on startup."""

    AUTO_FOCUS = None

    BINDINGS = [
        Binding("any", "dismiss_welcome", show=False),
    ]

    DEFAULT_CSS = """
    WelcomeScreen {
        align: center middle;
        background: #0A0E14;
    }
    #welcome-container {
        width: 60;
        height: auto;
        padding: 2 4;
        border: round #0077B6;
        background: #1A1F2B;
    }
    #banner {
        color: #00B4D8;
        text-align: center;
    }
    #version {
        color: #5C6370;
        text-align: center;
        margin-bottom: 1;
    }
    #hints {
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="welcome-container"):
            yield Static(_BANNER, id="banner")
            yield Static(f"v{malibu.__version__}", id="version")
            yield Static(_HINTS, id="hints")

    def on_mount(self) -> None:
        """Schedule auto-transition after 3 seconds."""
        self.set_timer(3.0, self._transition)

    def on_key(self) -> None:
        """Transition on any keypress."""
        self._transition()

    def _transition(self) -> None:
        """Switch to the ChatScreen."""
        from malibu.tui.screens.chat import ChatScreen

        if self.is_current:
            self.app.switch_screen(ChatScreen())
