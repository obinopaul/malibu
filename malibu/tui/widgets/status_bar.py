"""Single-line status bar showing mode, model, tokens, git branch, and cwd."""

from __future__ import annotations

import subprocess
from pathlib import Path

from textual.reactive import reactive
from textual.widgets import Static


def _git_branch() -> str:
    """Return the current git branch name, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


class StatusBar(Static):
    """A single-line bar displaying session metadata.

    Sections are separated by `` | ``.
    """

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: #5C6370;
        padding: 0 1;
    }
    """

    mode_name: reactive[str] = reactive("code")
    model_id: reactive[str] = reactive("")
    input_tokens: reactive[int] = reactive(0)
    output_tokens: reactive[int] = reactive(0)
    git_branch: reactive[str] = reactive("")
    cwd: reactive[str] = reactive("")
    session_title: reactive[str] = reactive("")

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.git_branch = _git_branch()
        self.cwd = str(Path.cwd())

    # ---- public update helpers ----

    def update_mode(self, mode: str) -> None:
        """Set the current agent mode name."""
        self.mode_name = mode

    def update_model(self, model: str) -> None:
        """Set the current model identifier."""
        self.model_id = model

    def update_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Update token counts."""
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def update_cwd(self, path: str) -> None:
        """Update the displayed working directory."""
        self.cwd = path

    # ---- ChatScreen-compatible aliases ----

    def set_mode(self, mode: str) -> None:
        self.update_mode(mode)

    def set_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.update_usage(input_tokens, output_tokens)

    def set_session_title(self, title: str) -> None:
        self.session_title = title

    # ---- rendering ----

    def _watch_mode_name(self) -> None:
        self._refresh_bar()

    def _watch_model_id(self) -> None:
        self._refresh_bar()

    def _watch_input_tokens(self) -> None:
        self._refresh_bar()

    def _watch_output_tokens(self) -> None:
        self._refresh_bar()

    def _watch_git_branch(self) -> None:
        self._refresh_bar()

    def _watch_cwd(self) -> None:
        self._refresh_bar()

    def _watch_session_title(self) -> None:
        self._refresh_bar()

    def _refresh_bar(self) -> None:
        """Recompose the bar text from current reactive values."""
        parts: list[str] = []

        if self.mode_name:
            parts.append(f"mode: {self.mode_name}")

        if self.model_id:
            parts.append(f"model: {self.model_id}")

        parts.append(f"tokens: {self.input_tokens}in / {self.output_tokens}out")

        if self.git_branch:
            parts.append(f"git: {self.git_branch}")

        if self.cwd:
            parts.append(self.cwd)

        if self.session_title:
            parts.append(self.session_title)

        self.update(" | ".join(parts))
