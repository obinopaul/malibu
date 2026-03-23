"""Run-state model for the Malibu TUI prompt lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RunPhase(str, Enum):
    """High-level phases shown in the TUI."""

    IDLE = "idle"
    STARTING = "starting"
    THINKING = "thinking"
    PLANNING = "planning"
    TOOL_RUNNING = "tool_running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_USER = "waiting_user"
    STREAMING = "streaming"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class RunState:
    """Mutable snapshot of the current run state."""

    phase: RunPhase = RunPhase.IDLE
    label: str = "Ready"
    lock_input: bool = False
    details: str = ""

    @property
    def is_active(self) -> bool:
        return self.phase not in {RunPhase.IDLE, RunPhase.ERROR, RunPhase.CANCELLED}
