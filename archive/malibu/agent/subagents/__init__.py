"""Subagents for the Malibu agent.

In Deep Agents, subagents are no longer python classes, but are parsed from AGENTS.md YAML frontmatter inside `.malibu/agents` and `.built_in`.
"""

from malibu.agent.subagents.loader import list_subagents

__all__ = ["list_subagents"]
