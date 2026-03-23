"""Session state accumulator for the ACP client.

Wraps acp.contrib.SessionAccumulator to maintain a full view of the
session state (messages, tool calls, plan) across streaming updates.
"""

from __future__ import annotations

from typing import Any

from acp.contrib import SessionAccumulator, SessionSnapshot
from acp.schema import SessionNotification


class MalibuSessionAccumulator:
    """Per-session state accumulator tracking all updates.

    Delegates to the SDK's SessionAccumulator and adds convenience
    methods for querying session state.
    """

    def __init__(self) -> None:
        self._accumulators: dict[str, SessionAccumulator] = {}

    def get_or_create(self, session_id: str) -> SessionAccumulator:
        if session_id not in self._accumulators:
            self._accumulators[session_id] = SessionAccumulator()
        return self._accumulators[session_id]

    def process_update(self, session_id: str, update: Any) -> None:
        """Feed a session_update into the accumulator."""
        acc = self.get_or_create(session_id)
        notification = SessionNotification(session_id=session_id, update=update)
        acc.apply(notification)

    def snapshot(self, session_id: str) -> SessionSnapshot | None:
        """Get a snapshot of the current session state."""
        acc = self._accumulators.get(session_id)
        if acc is None:
            return None
        return acc.snapshot()

    def clear(self, session_id: str) -> None:
        """Clear accumulated state for a session."""
        self._accumulators.pop(session_id, None)
