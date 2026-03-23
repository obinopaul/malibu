"""Tests for malibu.agent.modes — mode definitions and interrupt config."""

from __future__ import annotations

from malibu.agent.modes import DEFAULT_MODES, INTERRUPT_ON_BY_MODE, get_interrupt_on


class TestDefaultModes:
    def test_current_mode_is_accept_edits(self):
        assert DEFAULT_MODES.current_mode_id == "accept_edits"

    def test_four_modes_available(self):
        assert len(DEFAULT_MODES.available_modes) == 4

    def test_mode_ids(self):
        ids = {m.id for m in DEFAULT_MODES.available_modes}
        assert ids == {"plan", "ask_before_edits", "accept_edits", "accept_everything"}

    def test_modes_have_names_and_descriptions(self):
        for mode in DEFAULT_MODES.available_modes:
            assert mode.name
            assert mode.description


class TestInterruptOnByMode:
    def test_ask_before_edits_requires_approval_for_edits(self):
        config = INTERRUPT_ON_BY_MODE["ask_before_edits"]
        assert isinstance(config["edit_file"], dict)
        assert isinstance(config["write_file"], dict)
        assert isinstance(config["execute"], dict)

    def test_ask_before_edits_skips_read_tools(self):
        config = INTERRUPT_ON_BY_MODE["ask_before_edits"]
        assert config["read_file"] is False
        assert config["ls"] is False
        assert config["grep"] is False

    def test_accept_edits_auto_approves_file_ops(self):
        config = INTERRUPT_ON_BY_MODE["accept_edits"]
        assert config["edit_file"] is False
        assert config["write_file"] is False

    def test_accept_edits_requires_approval_for_execute(self):
        config = INTERRUPT_ON_BY_MODE["accept_edits"]
        assert isinstance(config["execute"], dict)

    def test_accept_everything_empty(self):
        config = INTERRUPT_ON_BY_MODE["accept_everything"]
        assert config == {}


class TestGetInterruptOn:
    def test_known_mode(self):
        result = get_interrupt_on("accept_edits")
        assert result is INTERRUPT_ON_BY_MODE["accept_edits"]

    def test_unknown_mode_falls_back_to_restrictive(self):
        result = get_interrupt_on("nonexistent_mode")
        assert result is INTERRUPT_ON_BY_MODE["ask_before_edits"]
