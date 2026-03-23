"""Shared spinner lifecycle and status state."""

from __future__ import annotations

from dataclasses import dataclass

from malibu.tui.widgets.spinner import BRAILLE_FRAMES


@dataclass(slots=True)
class SpinnerState:
    spinner_id: str
    label: str


class SpinnerService:
    """Track active spinner labels and provide animated frames."""

    _frames = BRAILLE_FRAMES

    def __init__(self) -> None:
        self._active: dict[str, SpinnerState] = {}
        self._frame_index = 0
        self._paused = False

    def start(self, spinner_id: str, label: str) -> None:
        self._active[spinner_id] = SpinnerState(spinner_id=spinner_id, label=label)

    def stop(self, spinner_id: str) -> None:
        self._active.pop(spinner_id, None)

    def stop_all(self) -> None:
        self._active.clear()

    def pause_for_resize(self) -> None:
        self._paused = True

    def resume_after_resize(self) -> None:
        self._paused = False

    def next_frame(self) -> str:
        if not self._active:
            return ""
        if not self._paused:
            self._frame_index = (self._frame_index + 1) % len(self._frames)
        label = next(reversed(self._active.values())).label
        return f"{self._frames[self._frame_index]} {label}"

    def current_symbol(self) -> str:
        return self._frames[self._frame_index]

    def active_count(self) -> int:
        return len(self._active)
