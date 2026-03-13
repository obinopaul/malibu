"""SubAgentManager — registry, spawning, and execution of subagents.

The manager keeps a registry of available ``BaseSubAgent`` types and
provides a ``spawn()`` method that creates a short-lived agent graph
(via ``create_agent()``) scoped to the subagent's restricted tool set.
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver

from malibu.agent.subagents.ask_user import AskUserSubAgent
from malibu.agent.subagents.base import BaseSubAgent
from malibu.agent.subagents.code_explorer import CodeExplorerSubAgent
from malibu.agent.subagents.planner import PlannerSubAgent
from malibu.config import Settings


class SubAgentManager:
    """Manages subagent lifecycle: registration, spawning, and execution.

    Each ``spawn()`` call builds an isolated ``create_agent()`` graph with
    its own ``MemorySaver`` checkpointer so subagent state never leaks
    into the parent agent.
    """

    # Default subagent types shipped with Malibu.
    _BUILTIN_TYPES: dict[str, type[BaseSubAgent]] = {
        "code_explorer": CodeExplorerSubAgent,
        "planner": PlannerSubAgent,
        "ask_user": AskUserSubAgent,
    }

    def __init__(self) -> None:
        self._registry: dict[str, type[BaseSubAgent]] = dict(self._BUILTIN_TYPES)
        self._checkpointer = MemorySaver()

    # ── Registry ──────────────────────────────────────────────────

    def register(self, agent_type: str, cls: type[BaseSubAgent]) -> None:
        """Register a custom subagent type."""
        self._registry[agent_type] = cls

    def available_types(self) -> list[str]:
        """Return names of all registered subagent types."""
        return list(self._registry.keys())

    # ── Spawning ──────────────────────────────────────────────────

    async def spawn(
        self,
        agent_type: str,
        task: str,
        settings: Settings,
        cwd: str,
        *,
        model_id: str | None = None,
    ) -> str:
        """Spawn a subagent, run it to completion, and return its response.

        Args:
            agent_type: Key into the subagent registry (e.g. ``"planner"``).
            task: The natural-language task description for the subagent.
            settings: Application configuration (used to resolve the LLM).
            cwd: Working directory context passed to the subagent prompt.
            model_id: Optional LLM model override.

        Returns:
            The subagent's final text response.

        Raises:
            ValueError: If ``agent_type`` is not registered.
        """
        if agent_type not in self._registry:
            raise ValueError(
                f"Unknown subagent type '{agent_type}'. "
                f"Available: {', '.join(self._registry)}"
            )

        subagent_instance = self._registry[agent_type]()

        # Resolve model
        model: str | BaseChatModel = model_id or settings.llm_model
        if settings.llm_api_key or settings.llm_base_url:
            model = settings.create_llm()

        # Augment the subagent prompt with cwd context
        system_prompt = (
            f"{subagent_instance.get_system_prompt()}\n\n"
            f"Working directory: {cwd}\n"
        )

        # Build an isolated agent graph
        thread_id = f"subagent-{agent_type}-{uuid.uuid4().hex[:8]}"
        agent_graph = create_agent(
            model=model,
            tools=subagent_instance.get_tools(),
            system_prompt=system_prompt,
            checkpointer=self._checkpointer,
        )

        # Run to completion
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        final_state = await agent_graph.ainvoke(
            {"messages": [{"role": "user", "content": task}]},
            config=config,
        )

        # Extract the last assistant message
        messages = final_state.get("messages", [])
        for msg in reversed(messages):
            content = getattr(msg, "content", None) or ""
            role = getattr(msg, "type", None)
            if role == "ai" and content:
                return content

        return "(subagent produced no response)"
