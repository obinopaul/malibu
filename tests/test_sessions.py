"""Tests for malibu.server.sessions — SessionManager lifecycle."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from malibu.config import Settings
from malibu.server.sessions import SessionManager


@pytest.fixture
def settings():
    return Settings(
        database_url="sqlite+aiosqlite:///test.db",
        jwt_secret="test-secret-key-for-tests-only",
        llm_model="openai:gpt-4o-mini",
        llm_api_key="sk-test-key",
        allowed_paths=["."],
        log_level="DEBUG",
    )


@pytest.fixture
def mock_agent():
    a = MagicMock()
    a.astream = MagicMock()
    a.aget_state = MagicMock()
    return a


@pytest.fixture
def session_mgr(settings, mock_agent):
    with patch("malibu.server.sessions.build_agent", return_value=mock_agent):
        return SessionManager(settings)


class TestSessionManager:
    def test_create_session(self, session_mgr, mock_agent):
        with patch("malibu.server.sessions.build_agent", return_value=mock_agent):
            agent = session_mgr.create_session("sess-1", cwd="/tmp/test")
        assert agent is mock_agent
        assert session_mgr.get_agent("sess-1") is mock_agent
        assert session_mgr.get_cwd("sess-1") == "/tmp/test"

    def test_get_agent_returns_none_for_unknown(self, session_mgr):
        assert session_mgr.get_agent("unknown") is None

    def test_get_or_create_agent_creates_new(self, session_mgr, mock_agent):
        with patch("malibu.server.sessions.build_agent", return_value=mock_agent):
            agent = session_mgr.get_or_create_agent("new-sess", cwd="/tmp/work")
        assert agent is mock_agent
        assert session_mgr.get_cwd("new-sess") == "/tmp/work"

    def test_get_or_create_agent_returns_existing(self, session_mgr, mock_agent):
        with patch("malibu.server.sessions.build_agent", return_value=mock_agent):
            session_mgr.create_session("sess-2", cwd="/work")
        agent = session_mgr.get_or_create_agent("sess-2", cwd="/work")
        assert agent is mock_agent

    def test_set_mode_rebuilds_agent(self, session_mgr, mock_agent):
        new_agent = MagicMock()
        with patch("malibu.server.sessions.build_agent", return_value=mock_agent):
            session_mgr.create_session("sess-3", cwd="/work")
        with patch("malibu.server.sessions.build_agent", return_value=new_agent) as mock_build:
            session_mgr.set_mode("sess-3", "accept_everything")
        mock_build.assert_called_once()
        assert session_mgr.get_agent("sess-3") is new_agent
        assert session_mgr.get_mode("sess-3") == "accept_everything"

    def test_set_model(self, session_mgr, mock_agent, settings):
        new_agent = MagicMock()
        with patch("malibu.server.sessions.build_agent", return_value=mock_agent):
            session_mgr.create_session("sess-4", cwd="/work")
        with patch("malibu.server.sessions.build_agent", return_value=new_agent) as mock_build:
            session_mgr.set_model("sess-4", "anthropic:claude-sonnet-4-5")
        mock_build.assert_called_once()
        assert mock_build.call_args.kwargs["model_id"] == "anthropic:claude-sonnet-4-5"
        assert session_mgr.get_agent("sess-4") is new_agent
        assert session_mgr.get_model("sess-4") == "anthropic:claude-sonnet-4-5"

    def test_fork_session(self, session_mgr, mock_agent):
        with patch("malibu.server.sessions.build_agent", return_value=mock_agent):
            session_mgr.create_session("original", cwd="/work", mode_id="accept_edits")
            forked = session_mgr.fork_session("original", "forked", cwd="/work2")
        assert forked is mock_agent
        assert session_mgr.get_cwd("forked") == "/work2"
        assert session_mgr.get_mode("forked") == "accept_edits"

    def test_remove_session(self, session_mgr, mock_agent):
        with patch("malibu.server.sessions.build_agent", return_value=mock_agent):
            session_mgr.create_session("to-remove", cwd="/work")
        session_mgr.remove_session("to-remove")
        assert session_mgr.get_agent("to-remove") is None

    def test_remove_nonexistent_no_error(self, session_mgr):
        session_mgr.remove_session("does-not-exist")  # Should not raise

    def test_get_defaults_for_unknown_session(self, session_mgr, settings):
        assert session_mgr.get_cwd("unknown") == "."
        assert session_mgr.get_model("unknown") == settings.llm_model
