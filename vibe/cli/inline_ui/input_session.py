"""prompt_toolkit-based input handler for the inline UI.

Provides:
- Multiline editing (Shift+Enter for newline, Enter to submit)
- Slash command completion
- Path completion (@ prefix)
- Input history (file-backed)
- Vim/Emacs keybinding support
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, merge_completers
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys


class SlashCommandCompleter(Completer):
    """Completes slash commands from the command registry."""

    def __init__(self, commands: list[tuple[str, str]]) -> None:
        # commands: list of (name, description)
        self._commands = commands

    def get_completions(self, document: Any, complete_event: Any) -> Any:
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        prefix = text.lower()
        for name, desc in self._commands:
            if name.lower().startswith(prefix):
                yield Completion(
                    name,
                    start_position=-len(text),
                    display_meta=desc,
                )


class InputSession:
    """Wraps prompt_toolkit PromptSession with Malibu configuration."""

    def __init__(
        self,
        history_file: Path | str | None = None,
        commands: list[tuple[str, str]] | None = None,
    ) -> None:
        history: Any
        if history_file:
            history = FileHistory(str(history_file))
        else:
            history = InMemoryHistory()

        completers: list[Completer] = []
        if commands:
            completers.append(SlashCommandCompleter(commands))

        completer = merge_completers(completers) if completers else None

        kb = KeyBindings()

        @kb.add(Keys.Enter)
        def _submit(event: Any) -> None:
            """Enter submits the input."""
            event.current_buffer.validate_and_handle()

        @kb.add(Keys.Escape, Keys.Enter)
        def _newline(event: Any) -> None:
            """Escape+Enter inserts a newline (multiline editing)."""
            event.current_buffer.insert_text("\n")

        self.prompt_session: PromptSession[str] = PromptSession(
            history=history,
            completer=completer,
            complete_while_typing=True,
            key_bindings=kb,
            multiline=False,
        )

    def prompt(
        self,
        prefix: str = "> ",
        **kwargs: Any,
    ) -> str:
        """Show the input prompt and return the user's input."""
        return self.prompt_session.prompt(
            HTML(f"<b>{prefix}</b>"),
            **kwargs,
        )

    async def prompt_async(
        self,
        prefix: str = "> ",
        **kwargs: Any,
    ) -> str:
        """Async version of prompt()."""
        return await self.prompt_session.prompt_async(
            HTML(f"<b>{prefix}</b>"),
            **kwargs,
        )
