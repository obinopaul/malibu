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
    parts: list[str] = []
    for filename in _CONTEXT_FILES:
        ctx_path = Path(cwd) / filename
        if ctx_path.is_file():
            try:
                content = ctx_path.read_text(encoding="utf-8", errors="replace")
                parts.append(f"### {filename}\n{content}")
            except OSError:
                continue
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


def build_middleware_stack(mode_id: str) -> list:
    """Assemble the full middleware list for ``create_agent(middleware=...)``.

    Ordering: HITL first (so it intercepts before execution), then custom hooks.
    """
    middlewares: list = []

    hitl = build_hitl_middleware(mode_id)
    if hitl is not None:
        middlewares.append(hitl)

    middlewares.append(log_tool_calls)

    return middlewares
