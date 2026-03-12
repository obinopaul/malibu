"""Agent graph factory using ``create_agent()`` from ``langchain.agents``.

This is the correct LangChain 1.0+ pattern: a single ``create_agent()`` call
replaces manual ``StateGraph`` construction, ``ToolNode``, ``agent_node``, and
``should_continue`` routing.  ``create_agent()`` returns a compiled graph that
handles the agent loop, tool execution, and state management automatically.
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from malibu.agent.middleware import build_middleware_stack, load_local_context
from malibu.agent.prompts import build_system_prompt
from malibu.agent.tools import ALL_TOOLS
from malibu.config import Settings


def build_agent(
    *,
    settings: Settings,
    cwd: str,
    mode: str = "accept_edits",
    checkpointer: Any | None = None,
    model_id: str | None = None,
) -> CompiledStateGraph:
    """Build and return a compiled Malibu agent graph.

    Uses ``create_agent()`` from ``langchain.agents`` with:
    - Model from ``model_id`` (if provided) or ``settings.llm_model``
    - All Malibu tools
    - Mode-aware HITL middleware via ``HumanInTheLoopMiddleware``
    - Local-context-aware system prompt

    Args:
        settings: Application configuration.
        cwd: Working directory for the session.
        mode: Agent mode id (controls interrupt behaviour).
        checkpointer: LangGraph checkpointer. Defaults to ``MemorySaver()``.
        model_id: Override for the LLM model identifier.

    Returns:
        A compiled graph ready for streaming.
    """
    # Resolve model — either model string or a ChatModel instance
    model: str | BaseChatModel = model_id or settings.llm_model
    if settings.llm_api_key or settings.llm_base_url:
        # Need a model instance for custom API key / base URL
        model = settings.create_llm()

    # Build system prompt with optional local context
    extra_context = load_local_context(cwd)
    system_prompt = build_system_prompt(cwd=cwd, mode=mode, extra_context=extra_context)

    # Build middleware stack (HITL + logging)
    middleware = build_middleware_stack(mode)

    if checkpointer is None:
        checkpointer = MemorySaver()

    agent = create_agent(
        model=model,
        tools=ALL_TOOLS,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
        middleware=middleware,
    )

    return agent
