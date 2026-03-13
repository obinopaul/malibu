"""Shared protocol helpers for Malibu's rich TUI bridge."""

from __future__ import annotations

from typing import Any

TUI_BOOTSTRAP_METHOD = "tui_bootstrap"
TUI_INTERRUPT_METHOD = "tui_interrupt"
TUI_EVENT_NOTIFICATION = "tui_event"


def build_tui_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a serializable custom TUI event envelope."""
    return {
        "session_id": session_id,
        "event_type": event_type,
        "payload": payload or {},
    }


def extract_event_type(params: dict[str, Any]) -> str:
    """Return the TUI event type from a bridge payload."""
    return str(params.get("event_type", ""))


def extract_payload(params: dict[str, Any]) -> dict[str, Any]:
    """Return the payload dictionary from a bridge payload."""
    payload = params.get("payload")
    return payload if isinstance(payload, dict) else {}
