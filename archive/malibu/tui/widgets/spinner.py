"""Animated loading spinner widget using braille pattern characters."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget
from textual.timer import Timer


# Braille-pattern spinner frames for smooth animation.
BRAILLE_FRAMES: tuple[str, ...] = (
    "\u2801", "\u2802", "\u2804", "\u2840",
    "\u2880", "\u2820", "\u2810", "\u2808",
)


class SpinnerWidget(Widget):
    """An animated loading indicator with an optional label.

    Attributes:
        label: Optional text displayed next to the spinner.
    """

    DEFAULT_CSS = """
    SpinnerWidget {
        width: auto;
        height: 1;
    }
    """

    label: reactive[str] = reactive("")
    _frame_index: int = 0
    _timer: Timer | None = None

    def __init__(
        self,
        label: str = "",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.label = label

    def on_mount(self) -> None:
        """Start the animation timer when mounted."""
        self._timer = self.set_interval(1 / 10, self._advance_frame)

    def _advance_frame(self) -> None:
        """Move to the next spinner frame and refresh."""
        self._frame_index = (self._frame_index + 1) % len(BRAILLE_FRAMES)
        self.refresh()

    def render(self) -> str:
        """Render the current spinner frame with optional label."""
        frame = BRAILLE_FRAMES[self._frame_index]
        if self.label:
            return f"{frame} {self.label}"
        return frame

    def on_unmount(self) -> None:
        """Stop the timer when the widget is removed."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
