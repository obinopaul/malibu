from __future__ import annotations

from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Input

from vibe.cli.textual_ui.ansi_markdown import AnsiMarkdown
from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic
from vibe.cli.textual_ui.widgets.vscode_compat import VscodeCompatInput


class PlanOptionsApp(Container):
    """Bottom-panel app shown after the plan agent finishes.

    Presents the user with options for how to proceed with the generated plan.
    Follows the same architecture as ``ApprovalApp``: mounted via
    ``_switch_from_input``, posts messages handled by the main ``VibeApp``,
    and removed via ``_switch_to_input_app``.

    Options:
        1. Clear context and auto-accept edits (Shift+Tab)
        2. Manually approve edits
        3. Auto-accept edits
        4. Text input — reject current plan and provide feedback
    """

    can_focus = True
    can_focus_children = False

    OPTION_COUNT: ClassVar[int] = 3

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "select", "Select", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("1", "select_1", "Option 1", show=False),
        Binding("2", "select_2", "Option 2", show=False),
        Binding("3", "select_3", "Option 3", show=False),
    ]

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    class ImplementClearAutoAccept(Message):
        """User chose: clear context and auto-accept edits."""

        def __init__(self, plan_text: str) -> None:
            super().__init__()
            self.plan_text = plan_text

    class ImplementManualApprove(Message):
        """User chose: implement with manual edit approval."""

        def __init__(self, plan_text: str) -> None:
            super().__init__()
            self.plan_text = plan_text

    class ImplementAutoAccept(Message):
        """User chose: implement with auto-accept edits."""

        def __init__(self, plan_text: str) -> None:
            super().__init__()
            self.plan_text = plan_text

    class ReviseWithFeedback(Message):
        """User typed feedback to revise the plan."""

        def __init__(self, plan_text: str, feedback: str) -> None:
            super().__init__()
            self.plan_text = plan_text
            self.feedback = feedback

    class Cancelled(Message):
        """User pressed Escape to dismiss."""

    # ------------------------------------------------------------------
    # Init / compose
    # ------------------------------------------------------------------

    def __init__(self, plan_text: str) -> None:
        super().__init__(id="planoptions-app")
        self.plan_text = plan_text
        self.selected_option = 0
        self._editing_feedback = False

        self.title_widget: NoMarkupStatic | None = None
        self.option_widgets: list[NoMarkupStatic] = []
        self.feedback_prefix: NoMarkupStatic | None = None
        self.feedback_input: VscodeCompatInput | None = None
        self.feedback_static: NoMarkupStatic | None = None
        self.help_widget: NoMarkupStatic | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="plan-options-preview"):
            yield AnsiMarkdown(
                self.plan_text or "*No plan text captured.*",
                classes="plan-options-preview-text",
            )

        with Vertical(id="planoptions-content"):
            self.title_widget = NoMarkupStatic(
                "Would you like to proceed?", classes="plan-options-title"
            )
            yield self.title_widget

            for _ in range(self.OPTION_COUNT):
                widget = NoMarkupStatic("", classes="plan-option")
                self.option_widgets.append(widget)
                yield widget

            yield NoMarkupStatic("")

            with Horizontal(classes="plan-feedback-row"):
                self.feedback_prefix = NoMarkupStatic(
                    "  4. ", classes="plan-feedback-prefix"
                )
                yield self.feedback_prefix
                self.feedback_input = VscodeCompatInput(
                    placeholder="Type here to tell Malibu what to change",
                    classes="plan-feedback-input",
                )
                yield self.feedback_input
                self.feedback_static = NoMarkupStatic(
                    "Type here to tell Malibu what to change",
                    classes="plan-feedback-static",
                )
                yield self.feedback_static

            yield NoMarkupStatic("")
            self.help_widget = NoMarkupStatic(
                "↑↓ navigate  Enter select  1-3 quick select  ESC cancel",
                classes="plan-options-help",
            )
            yield self.help_widget

    async def on_mount(self) -> None:
        self._update_options()
        self._update_feedback_row()
        self.focus()

    # ------------------------------------------------------------------
    # Display updates
    # ------------------------------------------------------------------

    def _update_options(self) -> None:
        labels = [
            "Yes, clear context and auto-accept edits (Shift+Tab)",
            "Yes, and manually approve edits",
            "Yes, and auto-accept edits",
        ]

        for idx, (text, widget) in enumerate(
            zip(labels, self.option_widgets, strict=True)
        ):
            is_selected = not self._editing_feedback and idx == self.selected_option

            cursor = "› " if is_selected else "  "
            option_text = f"{cursor}{idx + 1}. {text}"
            widget.update(option_text)

            widget.remove_class("plan-option-cursor-selected")
            widget.remove_class("plan-option-action")
            widget.remove_class("plan-option-dim")

            if is_selected:
                widget.add_class("plan-option-cursor-selected")
                widget.add_class("plan-option-action")
            else:
                widget.add_class("plan-option-dim")

    def _update_feedback_row(self) -> None:
        if not self.feedback_input or not self.feedback_static or not self.feedback_prefix:
            return

        is_selected = not self._editing_feedback and self.selected_option == self.OPTION_COUNT
        has_text = bool(self.feedback_input.value)

        prefix_cursor = "› " if is_selected or self._editing_feedback else "  "
        self.feedback_prefix.update(f"{prefix_cursor}4. ")

        if self._editing_feedback:
            self.feedback_prefix.remove_class("plan-option-dim")
            self.feedback_prefix.add_class("plan-option-cursor-selected")
            self.feedback_prefix.add_class("plan-option-action")
            self.feedback_input.display = True
            self.feedback_static.display = False
        elif has_text:
            self.feedback_prefix.remove_class("plan-option-dim")
            self.feedback_prefix.remove_class("plan-option-cursor-selected")
            self.feedback_input.display = True
            self.feedback_static.display = False
        elif is_selected:
            self.feedback_prefix.remove_class("plan-option-dim")
            self.feedback_prefix.add_class("plan-option-cursor-selected")
            self.feedback_prefix.add_class("plan-option-action")
            self.feedback_input.display = False
            self.feedback_static.display = True
        else:
            self.feedback_prefix.add_class("plan-option-dim")
            self.feedback_prefix.remove_class("plan-option-cursor-selected")
            self.feedback_input.display = False
            self.feedback_static.display = True

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def action_move_up(self) -> None:
        if self._editing_feedback:
            return
        self.selected_option = max(0, self.selected_option - 1)
        self._update_options()
        self._update_feedback_row()

    def action_move_down(self) -> None:
        if self._editing_feedback:
            return
        self.selected_option = min(self.OPTION_COUNT, self.selected_option + 1)
        self._update_options()
        self._update_feedback_row()

    def action_select(self) -> None:
        if self._editing_feedback:
            self._submit_feedback()
            return
        self._handle_selection(self.selected_option)

    def action_select_1(self) -> None:
        if self._editing_feedback:
            return
        self.selected_option = 0
        self._update_options()
        self._update_feedback_row()
        self._handle_selection(0)

    def action_select_2(self) -> None:
        if self._editing_feedback:
            return
        self.selected_option = 1
        self._update_options()
        self._update_feedback_row()
        self._handle_selection(1)

    def action_select_3(self) -> None:
        if self._editing_feedback:
            return
        self.selected_option = 2
        self._update_options()
        self._update_feedback_row()
        self._handle_selection(2)

    def action_cancel(self) -> None:
        if self._editing_feedback:
            self._editing_feedback = False
            self._update_options()
            self._update_feedback_row()
            self.can_focus_children = False
            self.focus()
            return
        self.post_message(self.Cancelled())

    # ------------------------------------------------------------------
    # Selection handling
    # ------------------------------------------------------------------

    def _handle_selection(self, option: int) -> None:
        match option:
            case 0:
                self.post_message(
                    self.ImplementClearAutoAccept(plan_text=self.plan_text)
                )
            case 1:
                self.post_message(
                    self.ImplementManualApprove(plan_text=self.plan_text)
                )
            case 2:
                self.post_message(
                    self.ImplementAutoAccept(plan_text=self.plan_text)
                )
            case 3:
                self._enter_feedback_mode()

    def _enter_feedback_mode(self) -> None:
        self._editing_feedback = True
        self._update_options()
        self._update_feedback_row()
        self.can_focus_children = True
        if self.feedback_input:
            self.feedback_input.focus()

    def _submit_feedback(self) -> None:
        if not self.feedback_input:
            return
        feedback = self.feedback_input.value.strip()
        if not feedback:
            return
        self.post_message(
            self.ReviseWithFeedback(plan_text=self.plan_text, feedback=feedback)
        )

    # ------------------------------------------------------------------
    # Input event handling
    # ------------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter inside the feedback text input."""
        event.stop()
        if self._editing_feedback:
            self._submit_feedback()

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Clear placeholder display when user starts typing."""
        event.stop()

    def on_blur(self, event: events.Blur) -> None:
        """Keep focus on the widget (same pattern as ApprovalApp)."""
        if not self._editing_feedback:
            self.call_after_refresh(self.focus)
