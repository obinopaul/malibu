"""Slash-command system for the Malibu TUI."""

from malibu.tui.commands.base import BaseCommand, CommandContext
from malibu.tui.commands.registry import SlashCommandRegistry

from malibu.tui.commands.help_cmd import HelpCommand
from malibu.tui.commands.clear_cmd import ClearCommand
from malibu.tui.commands.mode_cmd import ModeCommand
from malibu.tui.commands.model_cmd import ModelCommand
from malibu.tui.commands.session_cmd import SessionCommand
from malibu.tui.commands.compact_cmd import CompactCommand
from malibu.tui.commands.config_cmd import ConfigCommand
from malibu.tui.commands.mcp_cmd import McpCommand
from malibu.tui.commands.plan_cmd import PlanCommand
from malibu.tui.commands.skills_cmd import SkillsCommand


def create_default_registry() -> SlashCommandRegistry:
    """Build a registry pre-loaded with all built-in commands."""
    registry = SlashCommandRegistry()
    for cmd in (
        HelpCommand(),
        ClearCommand(),
        ModeCommand(),
        ModelCommand(),
        SessionCommand(),
        CompactCommand(),
        ConfigCommand(),
        McpCommand(),
        PlanCommand(),
        SkillsCommand(),
    ):
        registry.register(cmd)
    return registry


__all__ = [
    "BaseCommand",
    "CommandContext",
    "SlashCommandRegistry",
    "create_default_registry",
    "HelpCommand",
    "ClearCommand",
    "ModeCommand",
    "ModelCommand",
    "SessionCommand",
    "CompactCommand",
    "ConfigCommand",
    "McpCommand",
    "PlanCommand",
    "SkillsCommand",
]
