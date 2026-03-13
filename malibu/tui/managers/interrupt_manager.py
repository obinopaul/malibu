"""Interrupt and inline prompt state for the Malibu TUI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class InterruptKind(str, Enum):
    """Interactive prompt types handled by the TUI."""

    NONE = "none"
    TOOL_APPROVAL = "tool_approval"
    PLAN_REVIEW = "plan_review"
    ASK_USER = "ask_user"


@dataclass(slots=True)
class ActiveInterrupt:
    """Current interactive prompt state."""

    kind: InterruptKind
    payload: dict[str, Any]
    controller: Any | None = None


class InterruptManager:
    """Track one active inline prompt at a time."""

    def __init__(self) -> None:
        self._active = ActiveInterrupt(kind=InterruptKind.NONE, payload={})

    @property
    def active_kind(self) -> InterruptKind:
        return self._active.kind

    @property
    def payload(self) -> dict[str, Any]:
        return self._active.payload

    @property
    def controller(self) -> Any | None:
        return self._active.controller

    def is_active(self) -> bool:
        return self._active.kind is not InterruptKind.NONE

    def enter(
        self,
        kind: InterruptKind,
        payload: dict[str, Any],
        controller: Any | None = None,
    ) -> None:
        self._active = ActiveInterrupt(kind=kind, payload=payload, controller=controller)

    def clear(self) -> None:
        self._active = ActiveInterrupt(kind=InterruptKind.NONE, payload={})
