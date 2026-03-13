"""Base class and context for all slash commands."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from malibu.tui.app import MalibuApp


@dataclass
class CommandContext:
    """Runtime context passed to every command execution."""

    app: "MalibuApp"
    conn: Any  # ACP Agent connection
    session_id: str


class BaseCommand(ABC):
    """Abstract base for a TUI slash command."""

    name: str
    description: str
    usage: str = ""

    @abstractmethod
    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        """Run the command.

        Args:
            ctx: The current command context (app, connection, session).
            args: Positional arguments supplied after the command name.
        """
        ...
