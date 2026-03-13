"""Data models for the hooks system.

Defines lifecycle events and configuration structures for hook commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HookEvent(str, Enum):
    """Lifecycle events that can trigger hooks."""

    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
    SUBAGENT_START = "SubagentStart"
    SUBAGENT_STOP = "SubagentStop"
    STOP = "Stop"
    PRE_COMPACT = "PreCompact"
    SESSION_END = "SessionEnd"


# Valid event names for config validation
VALID_EVENT_NAMES = {e.value for e in HookEvent}


@dataclass
class HookCommand:
    """A single hook command to execute."""

    command: str
    timeout: int = 60
    type: str = "command"

    def __post_init__(self) -> None:
        if self.timeout < 1:
            self.timeout = 1
        elif self.timeout > 600:
            self.timeout = 600


@dataclass
class HookMatcher:
    """A matcher that filters when hooks fire, with associated commands."""

    hooks: list[HookCommand] = field(default_factory=list)
    matcher: str | None = None
    _compiled_regex: re.Pattern[str] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.matcher:
            try:
                self._compiled_regex = re.compile(self.matcher)
            except re.error:
                self._compiled_regex = None

    def matches(self, value: str | None = None) -> bool:
        """Check if this matcher matches the given value.

        Args:
            value: Value to match against (e.g., tool name, agent type).
                   If None and matcher is None, matches everything.

        Returns:
            True if the matcher matches.
        """
        if self.matcher is None:
            return True
        if value is None:
            return True
        if self._compiled_regex is None:
            return self.matcher == value
        return self._compiled_regex.search(value) is not None


@dataclass
class HookConfig:
    """Top-level hooks configuration."""

    hooks: dict[str, list[HookMatcher]] = field(default_factory=dict)

    def has_hooks_for(self, event: HookEvent) -> bool:
        """Check if there are hooks registered for the given event."""
        return event.value in self.hooks and len(self.hooks[event.value]) > 0

    def get_matchers(self, event: HookEvent) -> list[HookMatcher]:
        """Get all matchers for a given event."""
        return self.hooks.get(event.value, [])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HookConfig":
        """Create HookConfig from a dictionary (e.g., from JSON/YAML config)."""
        hooks: dict[str, list[HookMatcher]] = {}

        for event_name, matchers_data in data.get("hooks", {}).items():
            if event_name not in VALID_EVENT_NAMES:
                continue  # Skip unknown events

            matchers = []
            for matcher_data in matchers_data:
                hook_commands = [
                    HookCommand(
                        command=h.get("command", ""),
                        timeout=h.get("timeout", 60),
                        type=h.get("type", "command"),
                    )
                    for h in matcher_data.get("hooks", [])
                ]
                matchers.append(
                    HookMatcher(
                        matcher=matcher_data.get("matcher"),
                        hooks=hook_commands,
                    )
                )
            hooks[event_name] = matchers

        return cls(hooks=hooks)
