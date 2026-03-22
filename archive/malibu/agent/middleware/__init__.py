"""Malibu agent middleware package.

Provides production-grade middleware for the agent pipeline:
- ChannelContextMiddleware  — inject channel/user metadata
- ContentFilterMiddleware   — block banned content
- PIIMiddleware             — redact personally identifiable information
- RateLimitMiddleware       — token-bucket rate limiting
- build_tool_permission_middleware — per-role tool filtering
- build_middleware_stack     — assemble the full HITL + hooks + logging stack
"""

from malibu.agent.middleware.channel_context import ChannelContextMiddleware
from malibu.agent.middleware.guardrails import ContentFilterMiddleware, PIIMiddleware
from malibu.agent.middleware.permissions import build_tool_permission_middleware
from malibu.agent.middleware.rate_limit import RateLimitMiddleware
from malibu.agent.middleware.stack import build_middleware_stack, load_local_context

__all__ = [
    "ChannelContextMiddleware",
    "ContentFilterMiddleware",
    "PIIMiddleware",
    "RateLimitMiddleware",
    "build_tool_permission_middleware",
    "build_middleware_stack",
    "load_local_context",
]
