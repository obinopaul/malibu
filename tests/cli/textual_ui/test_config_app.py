from __future__ import annotations

import pytest

from tests.conftest import build_test_vibe_config
from vibe.cli.textual_ui.widgets.config_app import ConfigApp
from vibe.core.tools.base import BaseToolConfig


def _get_setting(app: ConfigApp, key: str) -> dict[str, object]:
    return next(setting for setting in app.settings if setting["key"] == key)


def test_config_app_displays_web_provider_preferences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vibe.cli.textual_ui.widgets.config_app.get_saved_api_key",
        lambda env_var: "tvly-secret-1234" if env_var == "TAVILY_API_KEY" else None,
    )
    config = build_test_vibe_config(
        tools={
            "web_search": BaseToolConfig(provider_preference="ddgs"),
            "web_fetch": BaseToolConfig(provider_preference="http"),
        }
    )
    app = ConfigApp(config)
    app._build_settings()

    assert app._get_display_value(_get_setting(app, "web_search_provider")) == "DDGS"
    assert app._get_display_value(_get_setting(app, "web_fetch_provider")) == "HTTP"
    assert app._get_display_value(_get_setting(app, "tavily_api_key")) == "tvly...1234"


def test_config_app_converts_web_provider_changes_for_save() -> None:
    app = ConfigApp(build_test_vibe_config())
    app.changes = {
        "active_model": "gpt-5",
        "autocopy_to_clipboard": "Off",
        "web_search_provider": "DDGS",
        "web_fetch_provider": "HTTP",
    }

    assert app._convert_changes_for_save() == {
        "active_model": "gpt-5",
        "autocopy_to_clipboard": False,
        "tools": {
            "web_search": {"provider_preference": "ddgs"},
            "web_fetch": {"provider_preference": "http"},
        },
    }
