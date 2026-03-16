"""ToolPermissionMiddleware — per-user tool filtering.

Uses LangChain's ``@wrap_model_call`` runtime-context pattern:

1. Gateway resolves ``user_id -> role`` from the channel's
   ``user_roles`` config.
2. The resolved role is passed as
   ``context={"user_role": "editor"}`` when invoking the agent.
3. This middleware reads ``request.runtime.context.user_role``
   and removes tools the role is not allowed to use *before*
   the model sees them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from langchain.agents.middleware import wrap_model_call
import structlog

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from langchain.agents.middleware import ModelRequest, ModelResponse


def build_tool_permission_middleware(
    config: Any,
) -> Callable:
    """Return a ``@wrap_model_call`` middleware closed over *config*.

    Filters the tool list on every model call based on the user's
    role (from ``request.runtime.context.user_role``).

    Args:
        config: A permissions config object with ``default_role`` and
                ``roles`` attributes.
    """

    @wrap_model_call
    async def _tool_permission_filter(
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        runtime = request.runtime
        ctx = getattr(runtime, "context", None) if runtime else None
        if ctx is not None:
            user_role = getattr(ctx, "user_role", config.default_role)
        else:
            user_role = config.default_role

        role_cfg = config.roles.get(user_role)
        if role_cfg is None or "*" in role_cfg.tools:
            logger.debug(
                "permissions_allow_all",
                role=user_role,
            )
            return await handler(request)

        allowed = set(role_cfg.tools)
        filtered = [t for t in request.tools if t.name in allowed]
        logger.debug(
            "permissions_filter_tools",
            role=user_role,
            allowed=list(allowed),
        )

        return await handler(request.override(tools=filtered))

    return _tool_permission_filter


__all__ = [
    "build_tool_permission_middleware",
]
