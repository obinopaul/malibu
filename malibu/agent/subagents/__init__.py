"""Subagent system for the Malibu agent.

Provides specialised, tool-restricted subagents that the main orchestrator
can delegate to for focused tasks like code exploration, planning, and
user interaction.
"""

from malibu.agent.subagents.ask_user import AskUserSubAgent
from malibu.agent.subagents.base import BaseSubAgent
from malibu.agent.subagents.code_explorer import CodeExplorerSubAgent
from malibu.agent.subagents.manager import SubAgentManager
from malibu.agent.subagents.planner import PlannerSubAgent

__all__ = [
    "BaseSubAgent",
    "CodeExplorerSubAgent",
    "PlannerSubAgent",
    "AskUserSubAgent",
    "SubAgentManager",
]
