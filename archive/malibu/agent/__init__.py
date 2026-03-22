"""Lazy public exports for the Malibu agent package."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ALL_TOOLS",
    "DEFAULT_MODES",
    "SessionMeta",
    "build_agent",
    "build_middleware_stack",
    "build_system_prompt",
    "get_interrupt_on",
    "load_local_context",
]


def __getattr__(name: str):
    if name == "build_agent":
        return import_module("malibu.agent.graph").build_agent
    if name in {"build_middleware_stack", "load_local_context"}:
        module = import_module("malibu.agent.middleware")
        return getattr(module, name)
    if name in {"DEFAULT_MODES", "get_interrupt_on"}:
        module = import_module("malibu.agent.modes")
        return getattr(module, name)
    if name == "build_system_prompt":
        return import_module("malibu.agent.prompts").build_system_prompt
    if name == "SessionMeta":
        return import_module("malibu.agent.state").SessionMeta
    if name == "ALL_TOOLS":
        return import_module("malibu.agent.tools").ALL_TOOLS
    raise AttributeError(f"module 'malibu.agent' has no attribute {name!r}")
