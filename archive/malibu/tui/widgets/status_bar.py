"""Compact Cloud Code-inspired status line for the Malibu TUI."""

from __future__ import annotations

from pathlib import Path

from textual.reactive import reactive
from textual.widgets import Static


class StatusBar(Static):
    """Single-line session and processing status."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $foreground;
        border-bottom: solid $panel-lighten-1;
    }
    """

    mode_name: reactive[str] = reactive("accept_edits")
    model_id: reactive[str] = reactive("")
    session_title: reactive[str] = reactive("New Session")
    cwd: reactive[str] = reactive("")
    input_tokens: reactive[int] = reactive(0)
    output_tokens: reactive[int] = reactive(0)
    queue_depth: reactive[int] = reactive(0)
    spinner_text: reactive[str] = reactive("")

    def __init__(self, *, cwd: str = ".") -> None:
        super().__init__(id="status-bar")
        self.cwd = str(Path(cwd).resolve())
        self._render_bar()

    def set_mode(self, mode: str) -> None:
        self.mode_name = mode

    def set_model(self, model_id: str) -> None:
        self.model_id = model_id

    def set_session_title(self, title: str) -> None:
        self.session_title = title

    def set_cwd(self, cwd: str) -> None:
        self.cwd = cwd

    def set_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def set_queue_depth(self, depth: int) -> None:
        self.queue_depth = depth

    def set_spinner(self, text: str) -> None:
        self.spinner_text = text

    def refresh_theme(self) -> None:
        self._render_bar()

    def watch_mode_name(self) -> None:
        self._render_bar()

    def watch_model_id(self) -> None:
        self._render_bar()

    def watch_session_title(self) -> None:
        self._render_bar()

    def watch_cwd(self) -> None:
        self._render_bar()

    def watch_input_tokens(self) -> None:
        self._render_bar()

    def watch_output_tokens(self) -> None:
        self._render_bar()

    def watch_queue_depth(self) -> None:
        self._render_bar()

    def watch_spinner_text(self) -> None:
        self._render_bar()

    def _render_bar(self) -> None:
        theme = getattr(self.app, "current_theme", None)
        accent = getattr(theme, "accent", None) or getattr(theme, "primary", None) or "#38bdf8"
        foreground = getattr(theme, "foreground", None) or "#e2e8f0"
        muted = getattr(theme, "variables", {}).get("foreground-muted", "#94a3b8") if theme else "#94a3b8"
        warning = getattr(theme, "warning", None) or "#f59e0b"
        success = getattr(theme, "success", None) or "#22c55e"
        cwd_name = Path(self.cwd).name or self.cwd
        parts = [
            f"[bold {accent}]malibu[/]",
            f"[{muted}]{self.session_title}[/]",
            f"[{foreground}]mode[/]=[{accent}]{self.mode_name}[/]",
        ]
        if self.model_id:
            parts.append(f"[{foreground}]model[/]=[{accent}]{self.model_id}[/]")
        parts.append(f"[{foreground}]tokens[/]={self.input_tokens}/{self.output_tokens}")
        if self.queue_depth:
            parts.append(f"[{warning}]queue[/]={self.queue_depth}")
        parts.append(f"[{muted}]{cwd_name}[/]")
        if self.spinner_text:
            parts.append(f"[{success}]{self.spinner_text}[/]")
        self.update("  ".join(parts))
