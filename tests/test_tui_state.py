from __future__ import annotations

from malibu.tui.managers.display_ledger import DisplayLedger
from malibu.tui.managers.message_history import MessageHistory
from malibu.tui.services.console_buffer import ConsoleBufferManager


def test_message_history_navigation_round_trip() -> None:
    history = MessageHistory()
    history.record_input("first")
    history.record_input("second")

    assert history.previous_input("") == "second"
    assert history.previous_input("") == "first"
    assert history.next_input() == "second"
    assert history.next_input() == ""


def test_display_ledger_deduplicates_within_turn() -> None:
    ledger = DisplayLedger()

    assert ledger.begin_user_turn("hello") is True
    assert ledger.allow_assistant_text("world") is True
    assert ledger.allow_assistant_text("world") is False
    ledger.complete_turn()
    assert ledger.begin_user_turn("hello") is True


def test_console_buffer_preview_truncates_long_output() -> None:
    buffers = ConsoleBufferManager(preview_lines=2, preview_chars=100)
    buffers.update("tool-1", "line1\nline2\nline3\nline4")

    preview, truncated = buffers.preview("tool-1")

    assert "line1" in preview
    assert "line2" in preview
    assert "line3" not in preview
    assert truncated is True
