"""Malibu context-engineering subsystem.

Provides production-safe context assembly for the agent runtime.
"""

from malibu.context_engineering.adapter import build_runtime_context

__all__ = ["build_runtime_context"]
