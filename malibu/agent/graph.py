"""Agent graph factory using ``create_agent()`` from ``langchain.agents``.

This is the correct LangChain 1.0+ pattern: a single ``create_agent()`` call
replaces manual ``StateGraph`` construction, ``ToolNode``, ``agent_node``, and
``should_continue`` routing.  ``create_agent()`` returns a compiled graph that
handles the agent loop, tool execution, and state management automatically.

Supports optional subagent delegation and skill tool injection.
"""

from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.local import LocalShellBackend
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from malibu.agent.prompts import build_system_prompt
from malibu.agent.tools import ALL_TOOLS
from malibu.config import Settings
from malibu.agent.middleware.channel_context import ChannelContextMiddleware
from malibu.agent.middleware.guardrails import ContentFilterMiddleware, PIIMiddleware
from malibu.agent.middleware.permissions import build_tool_permission_middleware
from malibu.agent.middleware.rate_limit import RateLimitMiddleware
from malibu.agent.middleware.stack import build_middleware_stack, load_local_context


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
    extra_middleware: list | None = None,
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
        extra_middleware: Optional list of additional middleware to append.

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

    # ── Middleware stack (order matters) ──────────────────────────
    #   1. ChannelContextMiddleware  — inject channel metadata first
    #   2. ToolPermission middleware — filter tools per-user role
    #   3. RateLimitMiddleware       — rate-check early
    #   4. ContentFilterMiddleware   — block banned content
    #   5. PIIMiddleware             — redact PII
    #   6. HITL + hooks + logging    — from build_middleware_stack
    #   7. Caller-provided extras

    middleware: list[Any] = [
        ChannelContextMiddleware(),
    ]

    # Tool permission filtering (if configured)
    if getattr(settings, "permissions", None) and getattr(settings.permissions, "enabled", False):
        middleware.append(
            build_tool_permission_middleware(settings.permissions),
        )

    # Rate limiting
    rate_limit_rpm = getattr(settings, "rate_limit_rpm", 60)
    middleware.append(RateLimitMiddleware(rpm=rate_limit_rpm))

    # Content filter
    banned_keywords = getattr(settings, "banned_keywords", [])
    if banned_keywords:
        middleware.append(ContentFilterMiddleware(banned_keywords=banned_keywords))

    # PII redaction
    middleware.append(PIIMiddleware())

    # HITL + hooks + logging stack
    middleware.extend(build_middleware_stack(mode, hook_manager=hook_manager))

    # Caller-provided extras
    if extra_middleware:
        middleware.extend(extra_middleware)

    if checkpointer is None:
        checkpointer = MemorySaver()

    # Merge tool lists
    tools = list(ALL_TOOLS)
    if extra_tools:
        tools.extend(extra_tools)

    # Create LocalShellBackend so Deep Agents provides filesystem tools natively
    backend = LocalShellBackend()

    # Load Subagents using our new module
    from malibu.agent.subagents.loader import list_subagents
    from deepagents.middleware.subagents import SubAgent
    
    loaded_subagents = list_subagents(
        user_agents_dir=Path(__file__).parent / "subagents" / "built_in",
        project_agents_dir=Path(cwd) / ".malibu" / "agents"
    )
    subagents: list[SubAgent] = []
    for meta in loaded_subagents:
        sa_dict: SubAgent = {
            "name": meta["name"],
            "description": meta["description"],
            "system_prompt": meta["system_prompt"],
        }
        if meta.get("model"):
            sa_dict["model"] = meta["model"]
        subagents.append(sa_dict)

    # Add ported middlewares
    from malibu.agent.middleware.local_context import LocalContextMiddleware
    from malibu.agent.middleware.ask_user import AskUserMiddleware
    
    middleware.append(LocalContextMiddleware(backend=backend))
    middleware.append(AskUserMiddleware())

    agent_kwargs: dict[str, Any] = {
        "model": model,
        "tools": tools,
        "system_prompt": system_prompt,
        "checkpointer": checkpointer,
        "middleware": middleware,
        "backend": backend,
        "subagents": subagents,
    }
    if callbacks:
        agent_kwargs["callbacks"] = callbacks

    agent = create_deep_agent(**agent_kwargs)

    return agent
