# vibe/cli/inline_ui/app.py
from __future__ import annotations

from vibe.core.agent_loop import AgentLoop


def run_inline_ui(
    agent_loop: AgentLoop,
    initial_prompt: str | None = None,
    teleport_on_start: bool = False,
) -> None:
    """Entry point for the Rich + prompt_toolkit inline UI."""
    raise NotImplementedError("Inline UI not yet implemented")
