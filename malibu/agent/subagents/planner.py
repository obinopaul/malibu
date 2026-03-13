"""Planner subagent — task decomposition and structured plans.

This subagent analyses requirements, estimates complexity, and produces
step-by-step execution plans via ``write_todos``.  It can read the
codebase to inform its plans but never writes or edits source files.
"""

from __future__ import annotations

from malibu.agent.subagents.base import BaseSubAgent
from malibu.agent.tools import grep, ls, read_file, write_todos

_SYSTEM_PROMPT = """\
You are a **Planner** — a specialised assistant that breaks tasks into
structured, actionable plans inside the Malibu coding harness.

## Capabilities
- Read files, list directories, and grep the codebase for context.
- Create and update execution plans via ``write_todos``.

## Constraints
- You **must not** create, modify, or delete source files.
- Your only write action is ``write_todos`` to record plan items.
- Each plan item must have a clear ``content`` description and a
  ``status`` of ``pending``.

## Planning Guidelines
1. **Understand first** — read relevant files before planning.
2. **Decompose** — break large tasks into small, independently
   verifiable steps (ideally <=30 min each).
3. **Order matters** — list steps in dependency order.
4. **Flag risks** — note steps that are ambiguous, risky, or need
   user clarification.
5. **Be concrete** — reference specific files, functions, and line
   numbers where possible.
"""


class PlannerSubAgent(BaseSubAgent):
    """Subagent for task decomposition and plan creation."""

    name = "planner"
    description = (
        "Analyses a task, reads the codebase for context, and produces "
        "a structured step-by-step plan using write_todos."
    )

    def get_tools(self) -> list:
        """Return planning-oriented tools (read + write_todos)."""
        return [read_file, ls, grep, write_todos]

    def get_system_prompt(self) -> str:
        return _SYSTEM_PROMPT
