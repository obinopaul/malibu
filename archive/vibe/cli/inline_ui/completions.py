# vibe/cli/inline_ui/completions.py
"""Completion adapters bridging existing autocompletion logic to prompt_toolkit."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from prompt_toolkit.completion import Completer, Completion


class CallbackCompleter(Completer):
    """Bridges any callback-based completion source to prompt_toolkit."""

    def __init__(
        self,
        get_completions_fn: Callable[[str, int], list[tuple[str, str]]],
    ) -> None:
        self._get_completions = get_completions_fn

    def get_completions(self, document: Any, complete_event: Any) -> Any:
        text = document.text_before_cursor
        cursor = document.cursor_position
        try:
            items = self._get_completions(text, cursor)
        except Exception:
            return
        for label, meta in items:
            yield Completion(
                label,
                start_position=-len(text),
                display_meta=meta,
            )
