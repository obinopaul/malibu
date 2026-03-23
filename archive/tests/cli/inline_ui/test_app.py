# tests/cli/inline_ui/test_app.py
from unittest.mock import MagicMock

import pytest

from vibe.cli.inline_ui.app import InlineApp


@pytest.fixture
def mocker_compat():
    """Minimal mocker-compatible object using unittest.mock."""
    class _Mocker:
        def MagicMock(self, *args, **kwargs):
            return MagicMock(*args, **kwargs)

    return _Mocker()


def test_inline_app_creates(mocker_compat):
    mock_loop = MagicMock()
    mock_loop.config.enable_notifications = False
    mock_loop.config.displayed_workdir = None
    mock_loop.config.get_active_model.return_value.alias = "test"
    mock_loop.config.get_active_model.return_value.auto_compact_threshold = 100000
    mock_loop.config.nuage_enabled = False
    mock_loop.skill_manager.available_skills = {}
    mock_loop.agent_profile.display_name = "default"
    mock_loop.agent_profile.safety = "safe"
    app = InlineApp(agent_loop=mock_loop)
    assert app is not None
