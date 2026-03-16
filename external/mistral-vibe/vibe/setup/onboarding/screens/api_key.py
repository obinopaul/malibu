from __future__ import annotations

from copy import deepcopy
import os
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Center, Horizontal, Vertical
from textual.events import MouseUp
from textual.validation import Length
from textual.widgets import Input, Link, Static

from vibe.cli.clipboard import copy_selection_to_clipboard
from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic
from vibe.core.config import Backend, VibeConfig
from vibe.core.config._settings import TomlFileSettingsSource
from vibe.core.config.credentials import save_api_key
from vibe.core.telemetry.send import TelemetryClient
from vibe.setup.onboarding.base import OnboardingScreen

PROVIDER_HELP = {
    "mistral": ("https://console.mistral.ai/codestral/cli", "Mistral AI Studio"),
    "openai": ("https://platform.openai.com/api-keys", "OpenAI Platform"),
    "anthropic": ("https://console.anthropic.com/settings/keys", "Anthropic Console"),
}
CONFIG_DOCS_URL = (
    "https://github.com/mistralai/mistral-vibe?tab=readme-ov-file#configuration"
)


class ApiKeyScreen(OnboardingScreen):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+c", "cancel", "Cancel", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    NEXT_SCREEN = None

    def __init__(self) -> None:
        super().__init__()
        config = VibeConfig.model_construct()
        active_model = config.get_active_model()
        self.provider = config.get_provider_for_model(active_model)

    def _resolve_provider(self) -> None:
        config = VibeConfig.model_construct()
        selected_provider_name = getattr(self.app, "selected_provider_name", None)
        if selected_provider_name:
            self.provider = config.get_provider(selected_provider_name)
            return
        active_model = config.get_active_model()
        self.provider = config.get_provider_for_model(active_model)

    def _compose_provider_link(self, provider_name: str) -> ComposeResult:
        if self.provider.name not in PROVIDER_HELP:
            return

        help_url, help_name = PROVIDER_HELP[self.provider.name]
        yield NoMarkupStatic(f"Grab your {provider_name} API key from the {help_name}:")
        yield Center(
            Horizontal(
                NoMarkupStatic("→ ", classes="link-chevron"),
                Link(help_url, url=help_url),
                classes="link-row",
            )
        )

    def _compose_config_docs(self) -> ComposeResult:
        yield Static("[dim]Learn more about Vibe configuration:[/]")
        yield Horizontal(
            NoMarkupStatic("→ ", classes="link-chevron"),
            Link(CONFIG_DOCS_URL, url=CONFIG_DOCS_URL),
            classes="link-row",
        )

    def compose(self) -> ComposeResult:
        self._resolve_provider()
        provider_name = self.provider.display_name

        self.input_widget = Input(
            password=True,
            id="key",
            placeholder="Paste your API key here",
            validators=[Length(minimum=1, failure_description="No API key provided.")],
        )

        with Vertical(id="api-key-outer"):
            yield NoMarkupStatic("", classes="spacer")
            yield Center(NoMarkupStatic("One last thing...", id="api-key-title"))
            with Center():
                with Vertical(id="api-key-content"):
                    yield from self._compose_provider_link(provider_name)
                    yield NoMarkupStatic(
                        "...and paste it below to finish the setup:", id="paste-hint"
                    )
                    yield Center(Horizontal(self.input_widget, id="input-box"))
                    yield NoMarkupStatic("", id="feedback")
            yield NoMarkupStatic("", classes="spacer")
            yield Vertical(
                Vertical(*self._compose_config_docs(), id="config-docs-group"),
                id="config-docs-section",
            )

    def on_mount(self) -> None:
        self._resolve_provider()
        self.input_widget.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        feedback = self.query_one("#feedback", NoMarkupStatic)
        input_box = self.query_one("#input-box")

        if event.validation_result is None:
            return

        input_box.remove_class("valid", "invalid")
        feedback.remove_class("error", "success")

        if event.validation_result.is_valid:
            feedback.update("Press Enter to submit ↵")
            feedback.add_class("success")
            input_box.add_class("valid")
            return

        descriptions = event.validation_result.failure_descriptions
        feedback.update(descriptions[0])
        feedback.add_class("error")
        input_box.add_class("invalid")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.validation_result and event.validation_result.is_valid:
            self._save_and_finish(event.value)

    def _save_and_finish(self, api_key: str) -> None:
        env_key = self.provider.api_key_env_var
        try:
            save_api_key(env_key, api_key)
        except OSError as err:
            self.app.exit(f"save_error:{err}")
            return
        os.environ[env_key] = api_key
        self._save_selected_provider_config()
        if self.provider.backend == Backend.MISTRAL:
            try:
                telemetry = TelemetryClient(config_getter=VibeConfig)
                telemetry.send_onboarding_api_key_added()
            except Exception:
                pass  # Telemetry is fire-and-forget; don't fail onboarding
        self.app.exit("completed")

    def _save_selected_provider_config(self) -> None:
        default_config = VibeConfig.model_construct()
        default_provider = default_config.get_provider(self.provider.name)
        default_models = default_config.get_models_for_provider(self.provider.name)
        default_model = default_config.get_default_model_for_provider(self.provider.name)

        current_config = TomlFileSettingsSource(VibeConfig).toml_data
        updated_config = deepcopy(current_config or VibeConfig.create_default())

        providers = updated_config.setdefault("providers", [])
        if not any(
            isinstance(provider, dict) and provider.get("name") == self.provider.name
            for provider in providers
        ):
            providers.append(default_provider.model_dump(mode="json", exclude_none=True))

        models = updated_config.setdefault("models", [])
        existing_aliases = {
            str(model.get("alias"))
            for model in models
            if isinstance(model, dict) and model.get("alias")
        }
        for model in default_models:
            if model.alias in existing_aliases:
                continue
            models.append(model.model_dump(mode="json", exclude_none=True))

        updated_config["active_model"] = default_model.alias
        VibeConfig.dump_config(updated_config)

    def on_mouse_up(self, event: MouseUp) -> None:
        copy_selection_to_clipboard(self.app)
