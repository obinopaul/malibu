from __future__ import annotations

from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.message import Message

from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic


class ModePickerApp(Container):
    """Bottom-panel picker for switching agent modes.

    Shows available modes with up/down navigation, enter to select,
    escape to cancel. Follows the same architecture as PlanOptionsApp.
    """

    can_focus = True
    can_focus_children = False

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "select", "Select", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    class ModeSelected(Message):
        """User picked a mode."""

        def __init__(self, mode_name: str) -> None:
            super().__init__()
            self.mode_name = mode_name

    class Cancelled(Message):
        """User pressed Escape."""

    # ------------------------------------------------------------------
    # Init / compose
    # ------------------------------------------------------------------

    def __init__(
        self,
        modes: list[tuple[str, str, str]],
        current_mode: str,
    ) -> None:
        """
        Args:
            modes: List of (name, display_name, description) tuples.
            current_mode: Name of the currently active mode.
        """
        super().__init__(id="modepicker-app")
        self._modes = modes
        self._current_mode = current_mode
        self.selected_index = 0
        self.title_widget: NoMarkupStatic | None = None
        self.option_widgets: list[NoMarkupStatic] = []
        self.help_widget: NoMarkupStatic | None = None

        # Pre-select the current mode
        for i, (name, _, _) in enumerate(modes):
            if name == current_mode:
                self.selected_index = i
                break

    def compose(self) -> ComposeResult:
        with Vertical(id="modepicker-content"):
            self.title_widget = NoMarkupStatic(
                "Switch Agent Mode", classes="mode-picker-title"
            )
            yield self.title_widget

            yield NoMarkupStatic("")

            for _ in self._modes:
                widget = NoMarkupStatic("", classes="mode-option")
                self.option_widgets.append(widget)
                yield widget

            yield NoMarkupStatic("")
            self.help_widget = NoMarkupStatic(
                "↑↓ navigate  Enter select  ESC cancel",
                classes="mode-picker-help",
            )
            yield self.help_widget

    async def on_mount(self) -> None:
        self._update_options()
        self.focus()

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _update_options(self) -> None:
        for idx, ((name, display_name, description), widget) in enumerate(
            zip(self._modes, self.option_widgets, strict=True)
        ):
            is_selected = idx == self.selected_index
            is_current = name == self._current_mode

            cursor = "› " if is_selected else "  "
            current_marker = " (current)" if is_current else ""
            option_text = f"{cursor}{display_name}{current_marker}  —  {description}"
            widget.update(option_text)

            widget.remove_class("mode-option-selected")
            widget.remove_class("mode-option-dim")

            if is_selected:
                widget.add_class("mode-option-selected")
            else:
                widget.add_class("mode-option-dim")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def action_move_up(self) -> None:
        self.selected_index = (self.selected_index - 1) % len(self._modes)
        self._update_options()

    def action_move_down(self) -> None:
        self.selected_index = (self.selected_index + 1) % len(self._modes)
        self._update_options()

    def action_select(self) -> None:
        name, _, _ = self._modes[self.selected_index]
        self.post_message(self.ModeSelected(mode_name=name))

    def action_cancel(self) -> None:
        self.post_message(self.Cancelled())

    def on_blur(self, event: events.Blur) -> None:
        self.call_after_refresh(self.focus)
