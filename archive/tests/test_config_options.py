"""Tests for malibu.server.config_options module."""

from __future__ import annotations

from malibu.server.config_options import ConfigOptionManager


def test_empty_session_config():
    mgr = ConfigOptionManager()
    config = mgr.get_config("sess-1")
    assert config == {}


def test_set_valid_option():
    mgr = ConfigOptionManager()
    update = mgr.set_option("sess-1", "temperature", "0.5")
    assert update is not None
    config = mgr.get_config("sess-1")
    assert config["temperature"] == 0.5


def test_set_invalid_option_returns_none():
    mgr = ConfigOptionManager()
    result = mgr.set_option("sess-1", "nonexistent_config", "bad")
    assert result is None


def test_set_out_of_range_returns_none():
    mgr = ConfigOptionManager()
    result = mgr.set_option("sess-1", "temperature", "5.0")
    assert result is None  # max is 2.0


def test_set_bad_type_returns_none():
    mgr = ConfigOptionManager()
    result = mgr.set_option("sess-1", "max_tokens", "not_a_number")
    assert result is None


def test_clear_session():
    mgr = ConfigOptionManager()
    mgr.set_option("sess-1", "temperature", "0.8")
    mgr.clear_session("sess-1")
    assert mgr.get_config("sess-1") == {}


def test_multiple_sessions_independent():
    mgr = ConfigOptionManager()
    mgr.set_option("sess-1", "temperature", "0.5")
    mgr.set_option("sess-2", "temperature", "1.0")
    assert mgr.get_config("sess-1")["temperature"] == 0.5
    assert mgr.get_config("sess-2")["temperature"] == 1.0


def test_build_session_config_options_returns_all():
    mgr = ConfigOptionManager()
    options = mgr.build_session_config_options("sess-1")
    # Should return all 4 config options with defaults
    assert len(options) == 4
    ids = {opt.root.id for opt in options}
    assert ids == {"temperature", "max_tokens", "context_window", "auto_approve_reads"}


def test_build_session_config_options_reflects_set_value():
    mgr = ConfigOptionManager()
    mgr.set_option("sess-1", "temperature", "1.5")
    options = mgr.build_session_config_options("sess-1")
    temp_opt = next(opt for opt in options if opt.root.id == "temperature")
    assert temp_opt.root.current_value == "1.5"


def test_build_session_config_options_valid_structure():
    mgr = ConfigOptionManager()
    options = mgr.build_session_config_options("sess-1")
    for opt in options:
        assert opt.root.type == "select"
        assert opt.root.name
        assert opt.root.id
        assert opt.root.current_value
        assert len(opt.root.options) > 0
