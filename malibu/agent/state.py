"""Agent state types for the Malibu harness.

With ``create_agent()`` from ``langchain.agents``, the agent manages its own
internal state (messages, tool calls, etc.).  This module only defines
auxiliary types that the *ACP server layer* tracks per-session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionMeta:
    """Per-session metadata tracked by the Malibu server (not LangGraph state)."""

    session_id: str
    cwd: str
    mode: str = "accept_edits"
    model: str = "openai:gpt-5.4"
    todos: list[dict[str, Any]] = field(default_factory=list)
