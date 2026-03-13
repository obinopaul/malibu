"""LangChain middleware for the Malibu agent.

Uses the official ``langchain.agents.middleware`` patterns:
  - ``HumanInTheLoopMiddleware`` for approval workflows
  - ``@wrap_tool_call`` for custom tool-level hooks (logging, context injection)

See the langchain-middleware skill for the canonical API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain.agents.middleware import HumanInTheLoopMiddleware, wrap_tool_call

from malibu.context_engineering.adapter import build_runtime_context
from malibu.agent.modes import get_interrupt_on


# ═══════════════════════════════════════════════════════════════════
# HITL middleware factory — builds per-mode approval middleware
# ═══════════════════════════════════════════════════════════════════

def build_hitl_middleware(mode_id: str) -> HumanInTheLoopMiddleware | None:
    """Return a ``HumanInTheLoopMiddleware`` configured for *mode_id*.

    Returns ``None`` for modes that have no tools requiring approval
    (e.g. ``accept_everything``).
    """
    interrupt_on = get_interrupt_on(mode_id)
    if not interrupt_on:
        return None
    return HumanInTheLoopMiddleware(interrupt_on=interrupt_on)


# ═══════════════════════════════════════════════════════════════════
# Local-context injection — reads .malibu/context.md, AGENTS.md, etc.
# ═══════════════════════════════════════════════════════════════════

_CONTEXT_FILES = [".malibu/context.md", ".malibu/instructions.md", "AGENTS.md"]


def load_local_context(cwd: str) -> str | None:
    """Read local context files from the session working directory.

    Returns concatenated content or ``None`` if no files are found.
    """
    try:
        context = build_runtime_context(cwd)
        if context:
            return context
    except Exception:
        # Fallback to legacy direct file loading.
        pass

    parts: list[str] = []
    for filename in _CONTEXT_FILES:
        ctx_path = Path(cwd) / filename
        if ctx_path.is_file():
            try:
                content = ctx_path.read_text(encoding="utf-8", errors="replace")
                parts.append(f"### {filename}\n{content}")
            except OSError:
                continue

    # Append git context if available
    try:
        from malibu.git.operations import get_git_context

        git_ctx = get_git_context(cwd)
        if git_ctx:
            parts.append(f"## Git Context\n{git_ctx}")
    except Exception:
        pass

    return "\n\n".join(parts) if parts else None


# ═══════════════════════════════════════════════════════════════════
# Tool-call logging middleware via @wrap_tool_call
# ═══════════════════════════════════════════════════════════════════

@wrap_tool_call
async def log_tool_calls(request: Any, handler: Any) -> Any:
    """Log every tool invocation for observability.

    This is a ``@wrap_tool_call`` middleware that the ``create_agent`` call
    includes in its ``middleware`` list.  The signature follows the
    ``wrap_tool_call`` contract: ``(request: ToolCallRequest, handler)``
    where ``handler(request)`` executes the tool.
    """
    from malibu.telemetry.logging import get_logger

    log = get_logger("malibu.agent.tools")
    tool_name = request.tool_call.get("name", "unknown") if isinstance(request.tool_call, dict) else str(request.tool_call)
    log.debug("tool_call_start", tool=tool_name)
    result = await handler(request)
    log.debug("tool_call_end", tool=tool_name)
    return result


# ═══════════════════════════════════════════════════════════════════
# Hook middleware — fires PRE_TOOL_USE / POST_TOOL_USE lifecycle events
# ═══════════════════════════════════════════════════════════════════

def _extract_tool_name(request: Any) -> str:
    """Extract the tool name from a middleware request."""
    if isinstance(request.tool_call, dict):
        return request.tool_call.get("name", "unknown")
    return str(request.tool_call)


def _extract_tool_args(request: Any) -> dict:
    """Extract the tool arguments from a middleware request."""
    if isinstance(request.tool_call, dict):
        return request.tool_call.get("args", {})
    return {}


def _build_hook_middleware(hook_manager: Any) -> Any:
    """Build a @wrap_tool_call middleware that fires hooks.

    Args:
        hook_manager: A HookManager instance.

    Returns:
        A wrap_tool_call-decorated middleware function.
    """
    from malibu.hooks.models import HookEvent

    @wrap_tool_call
    async def fire_hooks(request: Any, handler: Any) -> Any:
        tool_name = _extract_tool_name(request)
        tool_args = _extract_tool_args(request)

        # Fire PRE_TOOL_USE
        if hook_manager.has_hooks_for(HookEvent.PRE_TOOL_USE):
            outcome = hook_manager.run_hooks(
                HookEvent.PRE_TOOL_USE,
                match_value=tool_name,
                event_data={"tool": tool_name, "args": tool_args},
            )
            if outcome.blocked:
                return f"Blocked by hook: {outcome.block_reason}"

        # Execute tool
        result = await handler(request)

        # Fire POST_TOOL_USE
        if hook_manager.has_hooks_for(HookEvent.POST_TOOL_USE):
            hook_manager.run_hooks(
                HookEvent.POST_TOOL_USE,
                match_value=tool_name,
                event_data={"tool": tool_name, "args": tool_args, "result": str(result)[:2000]},
            )

        return result

    return fire_hooks


def build_middleware_stack(mode_id: str, *, hook_manager: Any | None = None) -> list:
    """Assemble the full middleware list for ``create_agent(middleware=...)``.

    Ordering: HITL first, then hooks, then logging.

    Args:
        mode_id: Agent mode for HITL configuration.
        hook_manager: Optional HookManager for lifecycle hooks.
    """
    middlewares: list = []

    hitl = build_hitl_middleware(mode_id)
    if hitl is not None:
        middlewares.append(hitl)

    if hook_manager is not None:
        middlewares.append(_build_hook_middleware(hook_manager))

    middlewares.append(log_tool_calls)

    return middlewares
