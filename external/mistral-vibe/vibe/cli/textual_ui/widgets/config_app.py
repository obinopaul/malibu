from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, TypedDict

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.message import Message
from textual.widgets import Input, Static

from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic
from vibe.core.config.credentials import get_saved_api_key, mask_secret

if TYPE_CHECKING:
    from vibe.core.config import ProviderConfig, VibeConfig


class SettingDefinition(TypedDict):
    key: str
    label: str
    type: str
    options: list[str]


class ConfigApp(Container):
    can_focus = True
    can_focus_children = False

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("space", "toggle_setting", "Toggle", show=False),
        Binding("enter", "cycle", "Next", show=False),
        Binding("escape", "close", "Close", show=False),
    ]

    class SettingChanged(Message):
        def __init__(self, key: str, value: str) -> None:
            super().__init__()
            self.key = key
            self.value = value

    class ConfigClosed(Message):
        def __init__(
            self,
            changes: dict[str, str | bool],
            env_updates: dict[str, str],
        ) -> None:
            super().__init__()
            self.changes = changes
            self.env_updates = env_updates

    def __init__(self, config: VibeConfig) -> None:
        super().__init__(id="config-app")
        self.config = config
        self.selected_index = 0
        self.changes: dict[str, str] = {}
        self.env_updates: dict[str, str] = {}
        self.selected_provider_name = config.get_active_model().provider
        preset_provider_names = [
            provider.name for provider in self.config.get_provider_options(preset_only=True)
        ]
        if self.selected_provider_name not in preset_provider_names and preset_provider_names:
            self.selected_provider_name = preset_provider_names[0]
        self._editing_secret = False

        self.settings: list[SettingDefinition] = []
        self.title_widget: Static | None = None
        self.setting_widgets: list[Static] = []
        self.help_widget: Static | None = None
        self.secret_input: Input | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="config-content"):
            self.title_widget = NoMarkupStatic("Settings", classes="settings-title")
            yield self.title_widget

            yield NoMarkupStatic("")

            self._build_settings()
            for _ in self.settings:
                widget = NoMarkupStatic("", classes="settings-option")
                self.setting_widgets.append(widget)
                yield widget

            yield NoMarkupStatic("")

            self.secret_input = Input(
                password=True,
                placeholder="Paste API key and press Enter",
                id="config-secret-input",
                classes="hidden",
            )
            yield self.secret_input

            self.help_widget = NoMarkupStatic(
                "↑↓ navigate  Space/Enter toggle  ESC exit", classes="settings-help"
            )
            yield self.help_widget

    def on_mount(self) -> None:
        self._build_settings()
        self._update_display()
        self.focus()

    def _build_settings(self) -> None:
        provider_options = [
            provider.name for provider in self.config.get_provider_options(preset_only=True)
        ]
        model_options = [model.alias for model in self._current_models()]
        self.settings = [
            {
                "key": "provider",
                "label": "Provider",
                "type": "cycle",
                "options": provider_options,
            },
            {
                "key": "active_model",
                "label": "Model",
                "type": "cycle",
                "options": model_options,
            },
            {
                "key": "api_key",
                "label": f"{self._current_provider().display_name} API key",
                "type": "secret",
                "options": [],
            },
            {
                "key": "autocopy_to_clipboard",
                "label": "Auto-copy",
                "type": "cycle",
                "options": ["On", "Off"],
            },
            {
                "key": "file_watcher_for_autocomplete",
                "label": "Autocomplete watcher (may delay first autocompletion)",
                "type": "cycle",
                "options": ["On", "Off"],
            },
        ]

    def _current_provider(self) -> ProviderConfig:
        return self.config.get_provider(self.selected_provider_name)

    def _current_models(self):
        return self.config.get_models_for_provider(self.selected_provider_name)

    def _current_model_alias(self) -> str:
        changed_model = self.changes.get("active_model")
        if changed_model and any(
            model.alias == changed_model for model in self._current_models()
        ):
            return changed_model
        return self.config.get_default_model_for_provider(self.selected_provider_name).alias

    def _get_display_value(self, setting: SettingDefinition) -> str:
        match setting["key"]:
            case "provider":
                return self._current_provider().display_name
            case "active_model":
                alias = self._current_model_alias()
                model = next(
                    model for model in self._current_models() if model.alias == alias
                )
                return model.display_name
            case "api_key":
                provider = self._current_provider()
                secret = (
                    self.env_updates.get(provider.api_key_env_var)
                    or get_saved_api_key(provider.api_key_env_var)
                )
                return mask_secret(secret)
            case key if key in self.changes:
                return self.changes[key]
            case key:
                raw_value = getattr(self.config, key, "")
                if isinstance(raw_value, bool):
                    return "On" if raw_value else "Off"
                return str(raw_value)

    def _update_display(self) -> None:
        self._build_settings()
        if len(self.setting_widgets) != len(self.settings):
            return

        for index, (setting, widget) in enumerate(
            zip(self.settings, self.setting_widgets, strict=True)
        ):
            is_selected = index == self.selected_index
            cursor = "› " if is_selected else "  "
            text = f"{cursor}{setting['label']}: {self._get_display_value(setting)}"
            widget.update(text)
            widget.remove_class("settings-value-cycle-selected")
            widget.remove_class("settings-value-cycle-unselected")
            widget.add_class(
                "settings-value-cycle-selected"
                if is_selected
                else "settings-value-cycle-unselected"
            )

        if self.help_widget:
            if self._editing_secret:
                provider = self._current_provider()
                self.help_widget.update(
                    f"Enter stores {provider.api_key_env_var} in ~/.vibe/.env  ESC cancels"
                )
            else:
                self.help_widget.update("↑↓ navigate  Space/Enter toggle  ESC exit")

    def action_move_up(self) -> None:
        if self._editing_secret:
            return
        self.selected_index = (self.selected_index - 1) % len(self.settings)
        self._update_display()

    def action_move_down(self) -> None:
        if self._editing_secret:
            return
        self.selected_index = (self.selected_index + 1) % len(self.settings)
        self._update_display()

    def action_toggle_setting(self) -> None:
        setting = self.settings[self.selected_index]
        match setting["key"]:
            case "provider":
                self._cycle_provider(setting["options"])
            case "active_model":
                self._cycle_model()
            case "api_key":
                self._open_secret_editor()
            case _:
                self._cycle_plain_setting(setting)

        self._update_display()

    def _cycle_provider(self, provider_names: list[str]) -> None:
        try:
            current_index = provider_names.index(self.selected_provider_name)
        except ValueError:
            current_index = -1
        self.selected_provider_name = provider_names[
            (current_index + 1) % len(provider_names)
        ]
        self.changes["active_model"] = self.config.get_default_model_for_provider(
            self.selected_provider_name
        ).alias
        self.post_message(
            self.SettingChanged(key="active_model", value=self.changes["active_model"])
        )

    def _cycle_model(self) -> None:
        models = self._current_models()
        aliases = [model.alias for model in models]
        current_alias = self._current_model_alias()
        try:
            current_index = aliases.index(current_alias)
        except ValueError:
            current_index = -1
        new_alias = aliases[(current_index + 1) % len(aliases)]
        self.changes["active_model"] = new_alias
        self.post_message(self.SettingChanged(key="active_model", value=new_alias))

    def _cycle_plain_setting(self, setting: SettingDefinition) -> None:
        key = setting["key"]
        current = self._get_display_value(setting)
        options = setting["options"]
        try:
            current_index = options.index(current)
        except ValueError:
            current_index = -1
        new_value = options[(current_index + 1) % len(options)]
        self.changes[key] = new_value
        self.post_message(self.SettingChanged(key=key, value=new_value))

    def _open_secret_editor(self) -> None:
        if self.secret_input is None:
            return
        provider = self._current_provider()
        current_value = (
            self.env_updates.get(provider.api_key_env_var)
            or get_saved_api_key(provider.api_key_env_var)
            or ""
        )
        self.secret_input.value = current_value
        self.secret_input.placeholder = f"Set {provider.api_key_env_var}"
        self.secret_input.remove_class("hidden")
        self.secret_input.focus()
        self._editing_secret = True

    def action_cycle(self) -> None:
        self.action_toggle_setting()

    def _convert_changes_for_save(self) -> dict[str, str | bool]:
        result: dict[str, str | bool] = {}
        for key, value in self.changes.items():
            if value in {"On", "Off"}:
                result[key] = value == "On"
            else:
                result[key] = value
        return result

    def action_close(self) -> None:
        if self._editing_secret:
            self._close_secret_editor()
            return
        self.post_message(
            self.ConfigClosed(
                changes=self._convert_changes_for_save(),
                env_updates=dict(self.env_updates),
            )
        )

    def _close_secret_editor(self) -> None:
        if self.secret_input is not None:
            self.secret_input.add_class("hidden")
        self._editing_secret = False
        self.focus()
        self._update_display()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.secret_input is None or event.input != self.secret_input:
            return
        provider = self._current_provider()
        value = event.value.strip()
        if value:
            self.env_updates[provider.api_key_env_var] = value
        self._close_secret_editor()

    def on_blur(self, event: events.Blur) -> None:
        del event
        if not self._editing_secret:
            self.call_after_refresh(self.focus)
