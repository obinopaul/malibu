"""Hooks system for Malibu — lifecycle event triggers.

Hooks allow custom commands to run at lifecycle events such as session
start, pre/post tool use, compaction, etc. Commands can add context,
modify inputs, or block actions.
"""

from malibu.hooks.models import HookEvent, HookConfig, HookCommand, HookMatcher
from malibu.hooks.manager import HookManager, HookOutcome
from malibu.hooks.loader import load_hooks_config
from malibu.hooks.executor import HookResult, HookCommandExecutor
from malibu.hooks.plugin_hooks import PluginHook, PluginHookManager

__all__ = [
    "HookEvent",
    "HookConfig",
    "HookCommand",
    "HookMatcher",
    "HookManager",
    "HookOutcome",
    "HookResult",
    "HookCommandExecutor",
    "load_hooks_config",
    "PluginHook",
    "PluginHookManager",
]
