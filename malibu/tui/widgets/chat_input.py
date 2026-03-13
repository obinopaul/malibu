"""Chat input widget with Enter-to-submit, command history, and slash-command detection."""

from __future__ import annotations

from textual.message import Message
from textual.widgets import TextArea
from textual import events


class ChatInput(TextArea):
    """A text input for composing messages.

    * **Enter** submits the current text (posts ``ChatInput.Submitted``).
    * **Shift+Enter** inserts a newline.
    * **Up / Down** arrows navigate command history when the input is empty.
    * Text starting with ``/`` is treated as a slash command.
    """

    DEFAULT_CSS = """
    ChatInput {
        height: auto;
        min-height: 3;
        max-height: 10;
        border: solid $primary;
        margin: 0 1;
    }
    """

    # ---- custom messages ----

    class Submitted(Message):
        """Posted when the user submits input (presses Enter)."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

        @property
        def is_command(self) -> bool:
            """Return ``True`` if the submitted text is a slash command."""
            return self.text.startswith("/")

    # ---- state ----

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._history: list[str] = []
        self._history_index: int = -1
        self._draft: str = ""

    # ---- key handling ----

    async def _on_key(self, event: events.Key) -> None:  # noqa: C901
        # Enter without Shift => submit
        if event.key == "enter" and not event.shift:
            event.prevent_default()
            event.stop()
            text = self.text.strip()
            if text:
                self._history.append(text)
                self._history_index = -1
                self._draft = ""
                self.clear()
                self.post_message(self.Submitted(text))
            return

        # Up arrow – navigate history backward when input is empty or already navigating
        if event.key == "up":
            if self.text.strip() == "" or self._history_index >= 0:
                event.prevent_default()
                event.stop()
                self._navigate_history(-1)
                return

        # Down arrow – navigate history forward
        if event.key == "down":
            if self._history_index >= 0:
                event.prevent_default()
                event.stop()
                self._navigate_history(1)
                return

    # ---- history helpers ----

    def _navigate_history(self, direction: int) -> None:
        """Move through command history.

        ``direction`` is -1 for older, +1 for newer.
        """
        if not self._history:
            return

        if self._history_index < 0:
            # Entering history mode — save current text as draft
            self._draft = self.text
            self._history_index = len(self._history)

        new_index = self._history_index + direction

        if new_index < 0:
            return

        if new_index >= len(self._history):
            # Moved past newest entry — restore draft
            self._history_index = -1
            self.clear()
            self.insert(self._draft)
            return

        self._history_index = new_index
        self.clear()
        self.insert(self._history[self._history_index])
