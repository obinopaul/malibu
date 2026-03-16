from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from malibu.tui.bridge import SessionUpdateMessage
from malibu.tui.commands.base import CommandContext
from malibu.tui.commands.clear_cmd import ClearCommand
from malibu.tui.commands.mode_cmd import ModeCommand
from malibu.tui.commands.model_cmd import ModelCommand
from malibu.tui.screens.option_picker import OptionPickerScreen


class _CommandApp:
    def __init__(self, *, selected: str | None, models: list[str] | None = None) -> None:
        self._selected = selected
        self._models = list(models or [])
        self.chat_screen = SimpleNamespace(action_clear_messages=MagicMock())
        self.new_session = AsyncMock()
        self.session_id: str | None = None
        self.pushed_screens: list[object] = []
        self.posted_messages: list[object] = []

    async def push_screen_wait(self, screen: object) -> str | None:
        self.pushed_screens.append(screen)
        return self._selected

    def get_model_candidates(self) -> list[str]:
        return list(self._models)

    def post_message(self, message: object) -> None:
        self.posted_messages.append(message)


async def test_mode_command_without_args_uses_picker_selection() -> None:
    app = _CommandApp(selected="accept_edits")
    conn = SimpleNamespace(set_session_mode=AsyncMock())
    ctx = CommandContext(app=app, conn=conn, session_id="sess-1")

    await ModeCommand().execute(ctx, [])

    conn.set_session_mode.assert_awaited_once_with(session_id="sess-1", mode_id="accept_edits")
    assert len(app.pushed_screens) == 1
    assert isinstance(app.pushed_screens[0], OptionPickerScreen)
    assert any(isinstance(message, SessionUpdateMessage) for message in app.posted_messages)


async def test_clear_command_uses_persistent_chat_screen() -> None:
    app = _CommandApp(selected=None)
    conn = SimpleNamespace()
    ctx = CommandContext(app=app, conn=conn, session_id="sess-1")

    await ClearCommand().execute(ctx, [])

    app.chat_screen.action_clear_messages.assert_called_once()
    app.new_session.assert_not_awaited()


async def test_clear_command_new_session_delegates_to_app() -> None:
    app = _CommandApp(selected=None)

    async def _new_session() -> None:
        app.session_id = "sess-2"

    app.new_session.side_effect = _new_session
    conn = SimpleNamespace()
    ctx = CommandContext(app=app, conn=conn, session_id="sess-1")

    await ClearCommand().execute(ctx, ["--new"])

    app.chat_screen.action_clear_messages.assert_called_once()
    app.new_session.assert_awaited_once()
    assert any(isinstance(message, SessionUpdateMessage) for message in app.posted_messages)


async def test_model_command_without_args_uses_picker_selection() -> None:
    app = _CommandApp(
        selected="anthropic:claude-sonnet-4-5",
        models=["openai:gpt-5.4", "anthropic:claude-sonnet-4-5"],
    )
    conn = SimpleNamespace(set_session_model=AsyncMock())
    ctx = CommandContext(app=app, conn=conn, session_id="sess-1")

    await ModelCommand().execute(ctx, [])

    conn.set_session_model.assert_awaited_once_with(
        session_id="sess-1",
        model_id="anthropic:claude-sonnet-4-5",
    )
    assert len(app.pushed_screens) == 1
    assert isinstance(app.pushed_screens[0], OptionPickerScreen)
    assert any(isinstance(message, SessionUpdateMessage) for message in app.posted_messages)
