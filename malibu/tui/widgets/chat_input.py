"""Rich chat input widget with history, large paste collapsing, and autocomplete."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from textual import events
from textual.message import Message
from textual.widgets import TextArea

if TYPE_CHECKING:
    from malibu.tui.managers.message_history import MessageHistory


@dataclass(frozen=True)
class CompletionItem:
    """Completion row plus the exact replacement range for insertion."""

    label: str
    value: str
    meta: str
    replace_start: int
    replace_end: int


CompletionProvider = Callable[[str, int], list[CompletionItem]]


class ChatTextArea(TextArea):
    """Text area with queued-completion updates and multiline submit rules."""

    DEFAULT_CSS = """
    ChatTextArea {
        height: 4;
        min-height: 4;
        max-height: 10;
        border: solid $panel-lighten-1;
        padding: 0 1;
        background: $surface;
        color: $foreground;
    }
    ChatTextArea:focus {
        border: solid $accent;
        background: $surface-active;
    }
    """

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class CompletionsChanged(Message):
        def __init__(self, items: list[tuple[str, str]], selected: int | None) -> None:
            super().__init__()
            self.items = items
            self.selected = selected

    def __init__(
        self,
        *,
        history: "MessageHistory | None" = None,
        completion_provider: CompletionProvider | None = None,
        paste_threshold: int = 400,
    ) -> None:
        super().__init__(id="chat-input", placeholder="Ask Malibu anything or press / for commands")
        self._history = history
        self._completion_provider = completion_provider
        self._paste_threshold = paste_threshold
        self._paste_replacements: dict[str, str] = {}
        self._paste_index = 0
        self._completion_timer = None
        self._completion_rows: list[CompletionItem] = []
        self._selected_completion: int | None = None

    def set_completion_provider(self, provider: CompletionProvider | None) -> None:
        self._completion_provider = provider

    def watch_text(self, _old: str, _new: str) -> None:
        self._schedule_completion_refresh()

    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        self._schedule_completion_refresh()

    def on_text_area_selection_changed(self, _event: TextArea.SelectionChanged) -> None:
        self._schedule_completion_refresh()

    async def _on_key(self, event: events.Key) -> None:
        if self._should_insert_newline(event):
            return

        if self._completion_rows and event.key in {"up", "down"} and not self.text.strip().count("\n"):
            event.prevent_default()
            event.stop()
            self._move_completion(-1 if event.key == "up" else 1)
            return

        if self._completion_rows and event.key == "tab":
            event.prevent_default()
            event.stop()
            self._accept_completion()
            return

        if self._is_submit_key(event):
            event.prevent_default()
            event.stop()
            text = self.text.strip()
            if not text:
                return
            resolved = self.resolve_large_pastes(text)
            if self._history is not None:
                self._history.record_input(resolved)
            self.clear()
            self.clear_large_pastes()
            self._clear_completions()
            self.post_message(self.Submitted(resolved))
            return

        if event.key == "up" and self._history is not None and not self.text.strip():
            previous = self._history.previous_input(self.text)
            if previous is not None:
                event.prevent_default()
                event.stop()
                self.load_text(previous)
            return

        if event.key == "down" and self._history is not None:
            newer = self._history.next_input()
            if newer is not None:
                event.prevent_default()
                event.stop()
                self.load_text(newer)
            return

    def _on_paste(self, event: events.Paste) -> None:
        pasted_text = event.text
        if len(pasted_text) <= self._paste_threshold:
            return
        event.prevent_default()
        event.stop()
        self._paste_index += 1
        token = f"[pasted-block-{self._paste_index}]"
        self._paste_replacements[token] = pasted_text
        self.insert(f"{token}\n")

    @staticmethod
    def _should_insert_newline(event: events.Key) -> bool:
        newline_keys = {"shift+enter", "ctrl+j", "alt+enter", "ctrl+enter", "newline"}
        if event.key in newline_keys:
            return True
        return any(alias in newline_keys for alias in event.aliases)

    @classmethod
    def _is_submit_key(cls, event: events.Key) -> bool:
        return event.key in {"enter", "return"} and not cls._should_insert_newline(event)

    def resolve_large_pastes(self, text: str) -> str:
        for token, value in self._paste_replacements.items():
            text = text.replace(token, value)
        return text

    def clear_large_pastes(self) -> None:
        self._paste_replacements.clear()

    def _schedule_completion_refresh(self) -> None:
        if self._completion_timer is not None:
            self._completion_timer.stop()
        self._completion_timer = self.set_timer(0.08, self._refresh_completions)

    def _refresh_completions(self) -> None:
        self._completion_timer = None
        if self._completion_provider is None or not self.text:
            self._clear_completions()
            return
        cursor = self.document.get_index_from_location(self.cursor_location)
        rows = self._completion_provider(self.text, cursor)
        self._completion_rows = rows
        self._selected_completion = 0 if rows else None
        self._emit_completions()

    def _move_completion(self, delta: int) -> None:
        if not self._completion_rows:
            return
        current = self._selected_completion or 0
        self._selected_completion = (current + delta) % len(self._completion_rows)
        self._emit_completions()

    def _accept_completion(self) -> None:
        if self._selected_completion is None or not self._completion_rows:
            return
        item = self._completion_rows[self._selected_completion]
        updated = f"{self.text[:item.replace_start]}{item.value}{self.text[item.replace_end:]}"
        self.load_text(updated)
        target_index = item.replace_start + len(item.value)
        self.cursor_location = self.document.get_location_from_index(target_index)
        self._clear_completions()

    def _emit_completions(self) -> None:
        items = [(item.label, item.meta) for item in self._completion_rows]
        self.post_message(self.CompletionsChanged(items, self._selected_completion))

    def _clear_completions(self) -> None:
        self._completion_rows = []
        self._selected_completion = None
        self.post_message(self.CompletionsChanged([], None))


class ChatInput(ChatTextArea):
    """Backward-compatible alias for the upgraded chat text area."""
