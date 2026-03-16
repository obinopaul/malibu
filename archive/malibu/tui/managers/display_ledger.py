"""Single display ledger for conversation rendering."""

from __future__ import annotations

import hashlib
from enum import Enum, auto


class TurnState(Enum):
    """Conversation turn state for deduplication and hydration."""

    IDLE = auto()
    USER = auto()
    ASSISTANT = auto()


class DisplayLedger:
    """Deduplicate user and assistant content across live and replay paths."""

    def __init__(self) -> None:
        self._turn_id = 0
        self._turn_state = TurnState.IDLE
        self._seen: set[tuple[int, str, str]] = set()

    @property
    def turn_id(self) -> int:
        return self._turn_id

    @property
    def turn_state(self) -> TurnState:
        return self._turn_state

    def begin_user_turn(self, text: str) -> bool:
        """Open a user turn if this message is not already rendered."""
        self._turn_id += 1
        allowed = self._record("user", text)
        if allowed:
            self._turn_state = TurnState.USER
        return allowed

    def allow_assistant_text(self, text: str) -> bool:
        """Return True when the assistant text should be rendered."""
        if not text.strip():
            return False
        allowed = self._record("assistant", text)
        if allowed:
            self._turn_state = TurnState.ASSISTANT
        return allowed

    def replay(self, role: str, text: str) -> None:
        """Register replayed content without opening a new live turn twice."""
        if role == "user":
            self._turn_id += 1
        self._record(role, text)

    def complete_turn(self) -> None:
        """Close the current turn and trim old hashes."""
        self._turn_state = TurnState.IDLE
        floor = max(0, self._turn_id - 1)
        self._seen = {
            (turn_id, role, value_hash)
            for turn_id, role, value_hash in self._seen
            if turn_id >= floor
        }

    def _record(self, role: str, text: str) -> bool:
        value_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        key = (self._turn_id, role, value_hash)
        if key in self._seen:
            return False
        self._seen.add(key)
        return True
