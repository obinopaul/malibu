# vibe/cli/inline_ui/notifications.py
"""Terminal notifications for the inline UI.

Sets terminal title and rings bell when action is required.
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from enum import Enum, auto


class NotificationContext(Enum):
    ACTION_REQUIRED = auto()
    COMPLETE = auto()


class InlineNotificationAdapter:
    """Notification adapter that uses raw ANSI escape sequences."""

    def __init__(
        self,
        get_enabled: Callable[[], bool] = lambda: True,
        default_title: str = "Malibu",
    ) -> None:
        self._get_enabled = get_enabled
        self._default_title = default_title
        self._has_focus = True

    def notify(self, context: NotificationContext) -> None:
        if not self._get_enabled():
            return
        if context == NotificationContext.ACTION_REQUIRED and not self._has_focus:
            self._set_title(f"[Action Required] {self._default_title}")
            self._bell()
        elif context == NotificationContext.COMPLETE and not self._has_focus:
            self._set_title(f"[Done] {self._default_title}")
            self._bell()

    def on_focus(self) -> None:
        self._has_focus = True
        self._set_title(self._default_title)

    def on_blur(self) -> None:
        self._has_focus = False

    def restore(self) -> None:
        self._set_title(self._default_title)

    def _set_title(self, title: str) -> None:
        sys.stdout.write(f"\033]0;{title}\007")
        sys.stdout.flush()

    def _bell(self) -> None:
        sys.stdout.write("\007")
        sys.stdout.flush()
