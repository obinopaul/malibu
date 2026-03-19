from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from vibe.core.deepagent.adapters import LANGCHAIN_AVAILABLE
from vibe.core.deepagent.runtime import (
    DEEPAGENT_AVAILABLE,
    DeepAgentDependencyError,
    DeepAgentRuntime,
    _SkillSourceMount,
    _StreamState,
)
from vibe.core.logger import logger
from vibe.core.types import (
    AssistantEvent,
    BaseEvent,
    LLMUsage,
    UserMessageEvent,
)

if TYPE_CHECKING:
    from vibe.core.agent_loop import AgentLoop


PLAN_COMMAND_TOOLS = frozenset({
    "read_file",
    "grep",
    "ast_grep",
    "todo",
    "task",
    "git",
    "bash",
    "ask_user_question",
})


class PlanAgentRuntime(DeepAgentRuntime):
    """Read-only planning agent built on DeepAgentRuntime.

    Inherits all stream processing, event extraction, and middleware from
    the parent class. Overrides only what differs:
    - Tool set is restricted to a read-only whitelist.
    - System prompt is plan-specific.
    - Skills are not mounted (the plan agent is focused on exploration).
    - Agent name is ``plan-agent``.
    - Uses its own thread ID so plan state is isolated from the main agent.
    """

    def __init__(self, loop: AgentLoop) -> None:
        super().__init__(loop)
        self._collected_text: list[str] = []
        self._plan_thread_id = str(uuid4())

    @property
    def collected_plan_text(self) -> str:
        """Return all assistant text collected during the plan run."""
        return "".join(self._collected_text)

    async def run(self, task: str) -> AsyncGenerator[BaseEvent]:
        """Run the planning agent on the given task, streaming events."""
        if not self.is_supported():
            msg = (
                "Plan agent requires 'deepagents', 'langchain', and "
                "'langgraph' packages."
            )
            raise DeepAgentDependencyError(msg)

        await self._ensure_agent()

        yield UserMessageEvent(content=task, message_id=str(uuid4()))

        async for event in self._stream_turn(task):
            if isinstance(event, AssistantEvent) and event.content:
                self._collected_text.append(event.content)
            yield event

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def _build_tools(self) -> list[Any]:
        """Build LangChain tools filtered to the read-only whitelist."""
        from vibe.core.deepagent.adapters import build_langchain_tools_filtered

        available = self._loop.tool_manager.available_tools
        filtered_names = sorted(
            name for name in available if name in PLAN_COMMAND_TOOLS
        )

        logger.info(
            "PlanAgentRuntime building %d read-only tools: %s",
            len(filtered_names),
            ", ".join(filtered_names),
        )

        return build_langchain_tools_filtered(
            self._loop,
            tool_names=filtered_names,
            emit_event=self._emit_side_event,
            on_tool_started=self._on_tool_started,
            on_tool_finished=self._on_tool_finished,
        )

    def _build_system_prompt(self) -> str:
        """Load the plan-specific system prompt."""
        prompt_path = Path(__file__).parent.parent / "prompts" / "plan_command.md"
        try:
            prompt_text = prompt_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            prompt_text = (
                "You are a planning agent. Explore the codebase thoroughly, "
                "then create a detailed, structured implementation plan. "
                "You cannot write or edit files — only read and analyze."
            )

        try:
            from deepagents.graph import BASE_AGENT_PROMPT

            return f"{prompt_text}\n\n{BASE_AGENT_PROMPT}"
        except ModuleNotFoundError:
            return prompt_text

    def _build_skill_mounts(self) -> list[_SkillSourceMount]:
        """Plan agent does not mount skills — focused on exploration."""
        return []

    def _build_middleware(
        self, *, model: Any, backend: Any, skill_mounts: list[_SkillSourceMount]
    ) -> list[Any]:
        """Build middleware without skills (plan agent has no skill mounts)."""
        try:
            from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
            from deepagents.middleware.summarization import (
                create_summarization_middleware,
            )
        except ModuleNotFoundError:
            return []

        return [
            create_summarization_middleware(model, backend),
            PatchToolCallsMiddleware(),
        ]

    def _create_agent_from_spec(self, spec: Any) -> Any:
        """Create the LangChain agent with plan-specific configuration."""
        try:
            from langchain.agents import create_agent
        except ModuleNotFoundError as exc:
            msg = "LangChain is required for PlanAgentRuntime"
            raise DeepAgentDependencyError(msg) from exc

        return create_agent(
            spec.model,
            system_prompt=spec.system_prompt,
            tools=spec.tools,
            middleware=spec.middleware,
            checkpointer=spec.checkpointer,
            name="plan-agent",
        ).with_config({
            "recursion_limit": 500,
            "metadata": {"ls_integration": "deepagents", "agent_kind": "plan"},
        })

    def _build_runnable_config(self) -> dict[str, Any]:
        """Use the plan agent's own thread ID for state isolation."""
        metadata: dict[str, str] = {}
        if self._loop.entrypoint_metadata:
            metadata.update(self._loop.entrypoint_metadata.model_dump())
        metadata["cwd"] = str(Path.cwd())
        metadata["agent_name"] = "plan-agent"
        return {
            "configurable": {"thread_id": self._plan_thread_id},
            "metadata": metadata,
        }
