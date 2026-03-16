"""Tests for malibu.server.sessions — SessionManager lifecycle."""

from __future__ import annotations

import json
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
    def test_register_session_persists_metadata_without_building_agent(self, session_mgr):
        with patch("malibu.server.sessions.build_agent") as mock_build:
            mode, model_id = session_mgr.register_session("sess-meta", cwd="/tmp/test")

        assert mode == "accept_edits"
        assert model_id == session_mgr.get_model("sess-meta")
        assert session_mgr.get_agent("sess-meta") is None
        assert session_mgr.get_cwd("sess-meta") == "/tmp/test"
        mock_build.assert_not_called()

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

    def test_warm_session_prebuilds_agent(self, session_mgr, mock_agent):
        with patch("malibu.server.sessions.build_agent", return_value=mock_agent) as mock_build:
            agent = session_mgr.warm_session("warm-sess", cwd="/warm")

        assert agent is mock_agent
        assert session_mgr.get_agent("warm-sess") is mock_agent
        mock_build.assert_called_once()

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

    def test_set_mode_updates_metadata_without_building_when_agent_not_loaded(self, session_mgr):
        session_mgr.register_session("sess-lazy-mode", cwd="/work")

        with patch("malibu.server.sessions.build_agent") as mock_build:
            session_mgr.set_mode("sess-lazy-mode", "accept_everything")

        assert session_mgr.get_mode("sess-lazy-mode") == "accept_everything"
        assert session_mgr.get_agent("sess-lazy-mode") is None
        mock_build.assert_not_called()

    def test_set_model_updates_metadata_without_building_when_agent_not_loaded(self, session_mgr):
        session_mgr.register_session("sess-lazy-model", cwd="/work")

        with patch("malibu.server.sessions.build_agent") as mock_build:
            session_mgr.set_model("sess-lazy-model", "anthropic:claude-sonnet-4-5")

        assert session_mgr.get_model("sess-lazy-model") == "anthropic:claude-sonnet-4-5"
        assert session_mgr.get_agent("sess-lazy-model") is None
        mock_build.assert_not_called()

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

    def test_list_session_summaries_omits_history(self, session_mgr, tmp_path):
        session_mgr._session_cache["sess-1"] = {
            "session_id": "sess-1",
            "cwd": str(tmp_path),
            "title": "Session One",
            "mode": "accept_edits",
            "model": "openai:gpt-4o-mini",
            "history": [{"kind": "session_update", "payload": {"big": "x" * 1000}}],
            "updated_at": "2026-03-14T00:00:00+00:00",
        }

        summaries = session_mgr.list_session_summaries()

        assert summaries == [
            {
                "session_id": "sess-1",
                "cwd": str(tmp_path),
                "title": "Session One",
                "mode": "accept_edits",
                "model": "openai:gpt-4o-mini",
                "updated_at": "2026-03-14T00:00:00+00:00",
            }
        ]

    def test_get_bootstrap_payload_compacts_large_history(self, session_mgr, tmp_path):
        history = [
            {
                "kind": "session_update",
                "payload": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": f"chunk-{index}-" + ("x" * 600)},
                },
            }
            for index in range(200)
        ]
        session_mgr._session_cache["sess-2"] = {
            "session_id": "sess-2",
            "cwd": str(tmp_path),
            "title": "Large Session",
            "mode": "accept_edits",
            "model": "openai:gpt-4o-mini",
            "config": {},
            "history": history,
            "updated_at": "2026-03-14T00:00:00+00:00",
        }
        session_mgr._cwds["sess-2"] = str(tmp_path)
        session_mgr._modes["sess-2"] = "accept_edits"
        session_mgr._models["sess-2"] = "openai:gpt-4o-mini"

        payload = session_mgr.get_bootstrap_payload("sess-2")
        encoded = json.dumps(payload, ensure_ascii=True).encode("utf-8")

        assert payload["history_truncated"] is True
        assert len(payload["history"]) < len(history)
        assert len(encoded) < 64_000

    def test_record_session_update_buffers_persistence_until_flush(self, session_mgr):
        session_mgr.register_session("sess-buffered", cwd="/work")
        update = MagicMock()
        update.model_dump.return_value = {"sessionUpdate": "agent_message_chunk"}

        with patch.object(session_mgr, "_save_record", wraps=session_mgr._save_record) as mock_save:
            session_mgr.record_session_update("sess-buffered", update)
            session_mgr.record_session_update("sess-buffered", update)

            assert mock_save.call_count == 0

            session_mgr.flush_session("sess-buffered")

        assert mock_save.call_count == 1
