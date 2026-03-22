"""Registry that maps slash-command names to their implementations."""

from __future__ import annotations

from malibu.tui.commands.base import BaseCommand


class SlashCommandRegistry:
    """Central lookup for all registered slash commands."""

    def __init__(self) -> None:
        self._commands: dict[str, BaseCommand] = {}

    def register(self, command: BaseCommand) -> None:
        """Register a command instance under its ``name``."""
        self._commands[command.name] = command

    def get(self, name: str) -> BaseCommand | None:
        """Return the command for *name*, or ``None`` if unknown."""
        return self._commands.get(name)

    def all(self) -> dict[str, BaseCommand]:
        """Return a snapshot of every registered command."""
        return dict(self._commands)

    def get_completions(self, prefix: str) -> list[str]:
        """Return command names that start with *prefix*.

        The prefix should **not** include the leading ``/``.
        """
        return sorted(
            name for name in self._commands if name.startswith(prefix)
        )

    @staticmethod
    def is_command(text: str) -> bool:
        """Return ``True`` if *text* looks like a slash command."""
        return text.startswith("/") and len(text) > 1 and not text.startswith("//")

    @staticmethod
    def parse(text: str) -> tuple[str, list[str]]:
        """Split *text* into ``(command_name, args_list)``.

        The leading ``/`` is stripped from the command name.
        """
        parts = text.strip().split()
        command_name = parts[0].lstrip("/")
        args = parts[1:] if len(parts) > 1 else []
        return command_name, args
