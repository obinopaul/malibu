from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Center, Vertical
from textual.widgets import Static

from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic
from vibe.core.config import VibeConfig
from vibe.core.config.credentials import get_saved_api_key
from vibe.setup.onboarding.base import OnboardingScreen


class ProviderPickerScreen(OnboardingScreen):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "next", "Next", show=False, priority=True),
        Binding("ctrl+c", "cancel", "Cancel", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    NEXT_SCREEN = "api_key"

    def __init__(self) -> None:
        super().__init__()
        self._config = VibeConfig.model_construct()
        self._providers = self._config.get_provider_options(preset_only=True)
        self._selected_index = 0
        self._provider_widgets: list[Static] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="provider-picker-container"):
            yield NoMarkupStatic("", classes="spacer")
            yield Center(NoMarkupStatic("Choose a model provider", id="provider-picker-title"))
            yield Center(
                NoMarkupStatic(
                    "You can change this later in /config or by editing ~/.vibe/config.toml.",
                    id="provider-picker-subtitle",
                )
            )
            yield NoMarkupStatic("")
            with Center():
                with Vertical(id="provider-picker-options"):
                    for _ in self._providers:
                        widget = NoMarkupStatic("", classes="provider-option")
                        self._provider_widgets.append(widget)
                        yield widget
            yield NoMarkupStatic("", classes="spacer")

    def on_mount(self) -> None:
        self._sync_app_selection()
        self._update_display()
        self.focus()

    def _sync_app_selection(self) -> None:
        app = self.app
        if getattr(app, "selected_provider_name", None):
            selected_name = app.selected_provider_name
        else:
            selected_name = self._config.get_active_model().provider
        for index, provider in enumerate(self._providers):
            if provider.name == selected_name:
                self._selected_index = index
                break
        self.app.selected_provider_name = self._providers[self._selected_index].name

    def _update_display(self) -> None:
        for index, (provider, widget) in enumerate(
            zip(self._providers, self._provider_widgets, strict=True)
        ):
            cursor = "› " if index == self._selected_index else "  "
            has_key = bool(
                provider.api_key_env_var
                and get_saved_api_key(provider.api_key_env_var) is not None
            )
            suffix = " (Configured)" if has_key else ""
            widget.update(f"{cursor}{provider.display_name}{suffix}")
            widget.remove_class("settings-value-cycle-selected")
            widget.remove_class("settings-value-cycle-unselected")
            widget.add_class(
                "settings-value-cycle-selected"
                if index == self._selected_index
                else "settings-value-cycle-unselected"
            )

    def action_move_up(self) -> None:
        self._selected_index = (self._selected_index - 1) % len(self._providers)
        self._sync_selected_provider()

    def action_move_down(self) -> None:
        self._selected_index = (self._selected_index + 1) % len(self._providers)
        self._sync_selected_provider()

    def _sync_selected_provider(self) -> None:
        self.app.selected_provider_name = self._providers[self._selected_index].name
        self._update_display()

    def action_next(self) -> None:
        self._sync_selected_provider()
        super().action_next()
