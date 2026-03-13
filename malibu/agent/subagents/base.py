"""Base class for Malibu subagents.

Every subagent declares a restricted tool set and a purpose-built system
prompt.  The ``SubAgentManager`` uses these to spawn a lightweight
``create_agent()`` graph scoped to a single sub-task.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseSubAgent(ABC):
    """Abstract base for all subagent types."""

    name: str
    description: str

    @abstractmethod
    def get_tools(self) -> list:
        """Return the restricted tool set for this subagent."""
        ...

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this subagent."""
        ...
