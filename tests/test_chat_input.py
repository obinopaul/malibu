from __future__ import annotations

from types import SimpleNamespace

from malibu.tui.widgets.chat_input import ChatInput


def _key_event(*, key: str, aliases: list[str] | None = None, character: str | None = None):
    return SimpleNamespace(key=key, aliases=aliases or [key], character=character)


def test_chat_input_treats_plain_enter_as_submit() -> None:
    event = _key_event(key="enter", aliases=["enter", "ctrl+m"], character="\r")

    assert ChatInput._is_submit_key(event) is True
    assert ChatInput._should_insert_newline(event) is False


def test_chat_input_treats_shift_enter_alias_as_newline() -> None:
    event = _key_event(key="shift+enter", aliases=["shift+enter", "enter"], character=None)

    assert ChatInput._should_insert_newline(event) is True
    assert ChatInput._is_submit_key(event) is False
