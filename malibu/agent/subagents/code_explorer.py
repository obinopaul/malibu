"""Code-explorer subagent — read-only codebase analysis.

This subagent is restricted to read-only tools and is designed for tasks
like understanding architecture, finding patterns, tracing call chains,
and explaining existing code.  It never modifies files.
"""

from __future__ import annotations

from malibu.agent.subagents.base import BaseSubAgent
from malibu.agent.tools import grep, ls, read_file

_SYSTEM_PROMPT = """\
You are a **Code Explorer** — a specialised read-only assistant embedded
inside the Malibu coding harness.

## Capabilities
- Read files, list directories, and search codebases with grep.
- Explain architecture, call chains, data flow, and design patterns.
- Locate definitions, usages, and cross-file relationships.

## Constraints
- You **must not** create, modify, or delete any file.
- You only have access to ``read_file``, ``ls``, and ``grep``.
- If a task requires writing code, say so clearly and hand back to the
  orchestrator.

## Output Guidelines
- Be precise: include file paths and line numbers when referencing code.
- Summarise first, then provide details if the user needs depth.
- When comparing approaches, use a concise pros/cons format.
"""


class CodeExplorerSubAgent(BaseSubAgent):
    """Read-only subagent for codebase exploration and analysis."""

    name = "code_explorer"
    description = (
        "Explores and analyses a codebase without making changes. "
        "Useful for understanding architecture, finding patterns, "
        "and explaining existing code."
    )

    def get_tools(self) -> list:
        """Return read-only filesystem tools."""
        return [read_file, ls, grep]

    def get_system_prompt(self) -> str:
        return _SYSTEM_PROMPT
