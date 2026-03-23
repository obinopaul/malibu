"""Compact composer-adjacent activity strip."""

from __future__ import annotations

from textual.widgets import Static

from malibu.tui.managers import RunPhase, RunState


class ActivityStrip(Static):
    """Single-line view of the current run state."""

    DEFAULT_CSS = """
    ActivityStrip {
        height: 1;
        padding: 0 1;
        color: $foreground;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="composer-status")
        self._mode_name = "accept_edits"
        self._queue_depth = 0
        self._shell_ready = False
        self._state = RunState()
        self._render_strip()

    def set_mode(self, mode_name: str) -> None:
        self._mode_name = mode_name
        self._render_strip()

    def set_queue_depth(self, depth: int) -> None:
        self._queue_depth = depth
        self._render_strip()

    def set_shell_ready(self, ready: bool) -> None:
        self._shell_ready = ready
        self._render_strip()

    def set_state(self, state: RunState) -> None:
        self._state = RunState(
            phase=state.phase,
            label=state.label,
            lock_input=state.lock_input,
            details=state.details,
        )
        self._render_strip()

    def refresh_theme(self) -> None:
        self._render_strip()

    def _render_strip(self) -> None:
        theme = getattr(self.app, "current_theme", None)
        accent = getattr(theme, "accent", None) or getattr(theme, "primary", None) or "#D7A77A"
        foreground = getattr(theme, "foreground", None) or "#F3EBDD"
        muted = getattr(theme, "variables", {}).get("foreground-muted", "#AA9988") if theme else "#AA9988"
        warning = getattr(theme, "warning", None) or "#C99A52"
        success = getattr(theme, "success", None) or "#879A63"
        error = getattr(theme, "error", None) or "#C25B4B"

        phase_label = {
            RunPhase.IDLE: "idle",
            RunPhase.STARTING: "starting",
            RunPhase.THINKING: "thinking",
            RunPhase.PLANNING: "planning",
            RunPhase.TOOL_RUNNING: "tool",
            RunPhase.WAITING_APPROVAL: "approval",
            RunPhase.WAITING_USER: "question",
            RunPhase.STREAMING: "streaming",
            RunPhase.ERROR: "error",
            RunPhase.CANCELLED: "cancelled",
        }[self._state.phase]
        phase_color = {
            RunPhase.IDLE: muted,
            RunPhase.STARTING: warning,
            RunPhase.THINKING: accent,
            RunPhase.PLANNING: accent,
            RunPhase.TOOL_RUNNING: warning,
            RunPhase.WAITING_APPROVAL: error,
            RunPhase.WAITING_USER: error,
            RunPhase.STREAMING: success,
            RunPhase.ERROR: error,
            RunPhase.CANCELLED: warning,
        }[self._state.phase]
        status_text = self._state.label or ("ready" if self._shell_ready else "starting local agent...")

        parts = [
            f"[{muted}]mode[/] [{accent}]{self._mode_name}[/]",
            f"[{muted}]phase[/] [{phase_color}]{phase_label}[/]",
            f"[{foreground}]{status_text}[/]",
        ]
        if self._state.details:
            parts.append(f"[{muted}]{self._state.details}[/]")
        if self._queue_depth:
            parts.append(f"[{warning}]queued {self._queue_depth}[/]")
        if self._state.lock_input:
            parts.append(f"[{error}]action required[/]")
        else:
            parts.append(f"[{muted}]shift+enter newline[/]")
        self.update("  •  ".join(parts))
