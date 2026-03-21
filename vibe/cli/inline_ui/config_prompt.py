# vibe/cli/inline_ui/config_prompt.py
"""Minimal config interaction for inline mode."""
from __future__ import annotations

from rich.console import Console
from rich.table import Table

from vibe.core.config import VibeConfig


def show_config(config: VibeConfig, console: Console | None = None) -> None:
    """Display current configuration."""
    console = console or Console(highlight=False)
    table = Table(title="Configuration", border_style="bright_black")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    active = config.get_active_model()
    table.add_row("Active Model", active.alias)
    table.add_row("Provider", str(config.get_provider_for_model(active).backend.value))
    table.add_row("Auto-approve", str(config.auto_approve))
    table.add_row("Web Search", str(getattr(config, "web_search_engine", "N/A")))

    console.print(table)
