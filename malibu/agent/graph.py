"""Agent graph factory using ``create_agent()`` from ``langchain.agents``.

This is the correct LangChain 1.0+ pattern: a single ``create_agent()`` call
replaces manual ``StateGraph`` construction, ``ToolNode``, ``agent_node``, and
``should_continue`` routing.  ``create_agent()`` returns a compiled graph that
handles the agent loop, tool execution, and state management automatically.

Supports optional subagent delegation and skill tool injection.
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
    extra_tools: list | None = None,
    extra_prompt: str | None = None,
    hook_manager: Any | None = None,
    callbacks: list | None = None,
) -> CompiledStateGraph:
    """Build and return a compiled Malibu agent graph.

    Uses ``create_agent()`` from ``langchain.agents`` with:
    - Model from ``model_id`` (if provided) or ``settings.llm_model``
    - All Malibu tools + optional extra tools (from skills, MCP, subagents)
    - Mode-aware HITL middleware via ``HumanInTheLoopMiddleware``
    - Local-context-aware system prompt
    - Optional callback handlers (e.g. cost tracking)

    Args:
        settings: Application configuration.
        cwd: Working directory for the session.
        mode: Agent mode id (controls interrupt behaviour).
        checkpointer: LangGraph checkpointer. Defaults to ``MemorySaver()``.
        model_id: Override for the LLM model identifier.
        extra_tools: Additional tools to include (from skills, MCP, subagents).
        extra_prompt: Additional prompt text to append (from skills).
        hook_manager: Optional HookManager for lifecycle hooks.
        callbacks: Optional list of LangChain callback handlers (e.g. CostTrackingCallback).

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
    # Combine local context with skills/extra prompt
    if extra_prompt:
        extra_context = f"{extra_context}\n\n{extra_prompt}" if extra_context else extra_prompt
    system_prompt = build_system_prompt(cwd=cwd, mode=mode, extra_context=extra_context)

    # Build middleware stack (HITL + hooks + logging)
    middleware = build_middleware_stack(mode, hook_manager=hook_manager)

    if checkpointer is None:
        checkpointer = MemorySaver()

    # Merge tool lists
    tools = list(ALL_TOOLS)
    if extra_tools:
        tools.extend(extra_tools)

    # Build create_agent kwargs — only pass callbacks if provided
    agent_kwargs: dict[str, Any] = {
        "model": model,
        "tools": tools,
        "system_prompt": system_prompt,
        "checkpointer": checkpointer,
        "middleware": middleware,
    }
    if callbacks:
        agent_kwargs["callbacks"] = callbacks

    agent = create_agent(**agent_kwargs)

    return agent
