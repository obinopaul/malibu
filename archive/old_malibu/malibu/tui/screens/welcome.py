"""WelcomeScreen — splash / landing screen for the Malibu TUI.

Displays an ASCII art banner, version information, and startup status while
the local agent session warms up.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Static

import malibu
from malibu.tui.widgets.spinner import SpinnerWidget

_BANNER = r"""
    __  ___      ___  _ __
   /  |/  /___ _/ (_)/ /_  __  __
  / /|_/ / __ `/ / / __ \/ / / /
 / /  / / /_/ / / / /_/ / /_/ /
/_/  /_/\__,_/_/_/_.___/\__,_/
"""

_STARTUP_HINTS = """\
[bold]Starting Malibu[/bold]
  Preparing the local session, loading tools, and warming the agent.
  This happens once at startup so the first prompt feels immediate.
"""

_READY_HINTS = """\
[bold]Quick start[/bold]
  Just start typing to chat with the agent.
  [dim]/help[/dim]  — list available commands
  [dim]/mode[/dim]  — switch agent mode
  [dim]ctrl+shift+p[/dim] — toggle plan panel
  [dim]ctrl+l[/dim] — clear conversation
"""


class WelcomeScreen(Screen):
    """Splash screen shown on startup."""

    AUTO_FOCUS = None
    startup_label: reactive[str] = reactive("Starting Malibu")
    startup_details: reactive[str] = reactive("Preparing the local session...")
    ready: reactive[bool] = reactive(False)

    BINDINGS = [
        Binding("any", "dismiss_welcome", show=False),
    ]

    DEFAULT_CSS = """
    WelcomeScreen {
        align: center middle;
        background: $background;
    }
    #welcome-container {
        width: 60;
        height: auto;
        padding: 2 4;
        border: round $accent;
        background: $panel;
    }
    #banner {
        color: $accent;
        text-align: center;
    }
    #version {
        color: $foreground-muted;
        text-align: center;
        margin-bottom: 1;
    }
    #startup {
        align-horizontal: center;
        margin-top: 1;
        margin-bottom: 1;
    }
    #startup-status {
        text-align: center;
        color: $foreground;
        margin-top: 1;
    }
    #startup-details {
        text-align: center;
        color: $foreground-muted;
        margin-top: 1;
    }
    #hints {
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="welcome-container"):
            yield Static(_BANNER, id="banner")
            yield Static(f"v{malibu.__version__}", id="version")
            yield SpinnerWidget("Starting Malibu", id="startup")
            yield Static(self.startup_label, id="startup-status")
            yield Static(self.startup_details, id="startup-details")
            yield Static(_STARTUP_HINTS, id="hints")

    def on_key(self) -> None:
        """Allow manual transition once startup is complete."""
        if self.ready:
            self._transition()

    def set_status(self, label: str, details: str = "") -> None:
        self.startup_label = label
        self.startup_details = details

    def set_ready(self, ready: bool = True) -> None:
        self.ready = ready
        if ready:
            self.startup_label = "Malibu is ready"
            if not self.startup_details:
                self.startup_details = "Launching the chat shell..."
            self.set_timer(0.35, self._transition)

    def watch_startup_label(self, label: str) -> None:
        if not self.is_mounted:
            return
        self.query_one("#startup", SpinnerWidget).label = label
        self.query_one("#startup-status", Static).update(label)

    def watch_startup_details(self, details: str) -> None:
        if not self.is_mounted:
            return
        self.query_one("#startup-details", Static).update(details)

    def watch_ready(self, ready: bool) -> None:
        if not self.is_mounted:
            return
        if ready:
            self.query_one("#hints", Static).update(_READY_HINTS)
        else:
            self.query_one("#hints", Static).update(_STARTUP_HINTS)

    def _transition(self) -> None:
        """Switch to the ChatScreen."""
        if self.is_current:
            if hasattr(self.app, "show_chat_screen"):
                self.app.show_chat_screen()  # type: ignore[attr-defined]
