"""Tests for malibu.server.agent — MalibuAgent protocol methods.

Tests the simpler protocol methods using mocked dependencies.
The complex prompt() method is tested at integration level.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from acp.schema import TextContentBlock

from malibu.config import Settings
from malibu.server.agent import MalibuAgent


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
def mock_conn():
    conn = MagicMock()
    conn.session_update = AsyncMock()
    conn.request_permission = AsyncMock()
    conn.ext_notification = AsyncMock()
    return conn


@pytest.fixture
def agent(settings, mock_conn):
    with patch("malibu.server.agent.SessionManager") as MockSessionMgr:
        mock_session_mgr = MockSessionMgr.return_value
        mock_session_mgr.register_session = MagicMock()
        mock_session_mgr.create_session = MagicMock()
        mock_session_mgr.get_agent = MagicMock(return_value=None)
        mock_session_mgr.get_or_create_agent = MagicMock()
        mock_session_mgr.get_bootstrap_payload = MagicMock(return_value={"session_title": "Session test"})
        mock_session_mgr.get_callbacks = MagicMock(return_value=[])
        mock_session_mgr.list_session_summaries = MagicMock(return_value=[])
        mock_session_mgr.get_model = MagicMock(return_value="openai:gpt-4o-mini")
        mock_session_mgr.flush_session = MagicMock()
        mock_session_mgr.warm_session = MagicMock()
        mock_session_mgr.get_cwd = MagicMock(return_value=".")
        mock_session_mgr.set_mode = MagicMock()
        mock_session_mgr.set_model = MagicMock()
        mock_session_mgr.fork_session = MagicMock()
        mock_session_mgr._agents = {}
        a = MalibuAgent(settings)
        a.on_connect(mock_conn)
        return a


class TestInitialize:
    async def test_initialize_returns_protocol_version(self, agent):
        resp = await agent.initialize(protocol_version=1)
        assert resp.protocol_version == 1

    async def test_initialize_returns_capabilities(self, agent):
        resp = await agent.initialize(protocol_version=1)
        assert resp.agent_capabilities is not None


class TestNewSession:
    async def test_new_session_returns_session_id(self, agent):
        resp = await agent.new_session(cwd="/tmp/test")
        assert resp.session_id
        assert len(resp.session_id) == 32  # uuid4().hex

    async def test_new_session_returns_modes(self, agent):
        resp = await agent.new_session(cwd="/tmp/test")
        assert resp.modes is not None
        assert resp.modes.current_mode_id == "accept_edits"

    async def test_new_session_creates_in_session_mgr(self, agent):
        await agent.new_session(cwd="/work")
        agent._session_mgr.register_session.assert_called_once()
        call_args = agent._session_mgr.register_session.call_args
        assert call_args.kwargs["cwd"] == "/work"


class TestLoadSession:
    async def test_load_session_returns_modes(self, agent):
        resp = await agent.load_session(cwd="/work", session_id="test-sess")
        assert resp.modes is not None
        agent._session_mgr.register_session.assert_called_once_with("test-sess", cwd="/work")

    async def test_load_session_existing(self, agent):
        agent._session_mgr.get_agent.return_value = MagicMock()
        resp = await agent.load_session(cwd="/work", session_id="test-sess")
        assert resp is not None


class TestListSessions:
    async def test_list_sessions_empty(self, agent):
        agent._session_mgr._agents = {}
        resp = await agent.list_sessions()
        assert resp.sessions == []

    async def test_list_sessions_with_sessions(self, agent):
        agent._session_mgr._agents = {"s1": MagicMock(), "s2": MagicMock()}
        agent._session_mgr.get_cwd = MagicMock(return_value="/work")
        resp = await agent.list_sessions()
        assert len(resp.sessions) == 2


class TestSetSessionMode:
    async def test_set_mode_calls_session_mgr(self, agent, mock_conn):
        await agent.set_session_mode(mode_id="accept_everything", session_id="s1")
        agent._session_mgr.set_mode.assert_called_once_with("s1", "accept_everything")

    async def test_set_mode_sends_update_to_client(self, agent, mock_conn):
        await agent.set_session_mode(mode_id="accept_everything", session_id="s1")
        mock_conn.session_update.assert_called_once()


class TestSetSessionModel:
    async def test_set_model(self, agent):
        resp = await agent.set_session_model(model_id="anthropic:claude-sonnet-4-5", session_id="s1")
        agent._session_mgr.set_model.assert_called_once_with("s1", "anthropic:claude-sonnet-4-5")
        assert resp is not None


class TestSetConfigOption:
    async def test_set_valid_config_returns_options(self, agent, mock_conn):
        resp = await agent.set_config_option(config_id="temperature", session_id="s1", value="0.5")
        assert resp is not None
        assert resp.config_options is not None
        assert len(resp.config_options) == 4

    async def test_set_valid_config_sends_update(self, agent, mock_conn):
        await agent.set_config_option(config_id="temperature", session_id="s1", value="0.5")
        mock_conn.session_update.assert_called_once()
        call_kwargs = mock_conn.session_update.call_args.kwargs
        assert call_kwargs["update"].session_update == "config_option_update"

    async def test_set_invalid_config_no_update(self, agent, mock_conn):
        resp = await agent.set_config_option(config_id="nonexistent", session_id="s1", value="bad")
        mock_conn.session_update.assert_not_called()
        # Should still return config_options (all defaults)
        assert resp.config_options is not None


class TestCancel:
    async def test_cancel_sets_flag(self, agent):
        await agent.cancel(session_id="s1")
        assert agent._cancelled["s1"] is True


class TestForkSession:
    async def test_fork_session_returns_new_id(self, agent):
        resp = await agent.fork_session(cwd="/work", session_id="original")
        assert resp.session_id
        assert resp.session_id != "original"
        assert resp.modes is not None


class TestResumeSession:
    async def test_resume_session_returns_modes(self, agent):
        resp = await agent.resume_session(cwd="/work", session_id="existing")
        assert resp.modes is not None
        agent._session_mgr.register_session.assert_called_once_with("existing", cwd="/work")


class TestExtMethod:
    async def test_ext_method_delegates(self, agent):
        agent._extensions.handle_method = AsyncMock(return_value={"result": "ok"})
        result = await agent.ext_method("custom.method", {"key": "val"})
        assert result == {"result": "ok"}


class TestExtNotification:
    async def test_ext_notification_delegates(self, agent):
        agent._extensions.handle_notification = AsyncMock()
        await agent.ext_notification("custom.notify", {"key": "val"})
        agent._extensions.handle_notification.assert_called_once()


class TestPrompt:
    async def test_prompt_emits_user_echo_before_agent_creation(self, agent):
        call_order: list[str] = []
        fake_graph = MagicMock()

        def _get_or_create(*args, **kwargs):
            call_order.append("get_or_create_agent")
            return fake_graph

        async def _emit_session_update(session_id, update):
            call_order.append(update.session_update)

        async def _emit_status(session_id, phase, label, **kwargs):
            call_order.append(f"status:{label}")

        async def _prompt_loop(**kwargs):
            call_order.append("prompt_loop")
            return SimpleNamespace(stop_reason="end_turn")

        agent._session_mgr.get_or_create_agent.side_effect = _get_or_create
        agent._emit_session_update = AsyncMock(side_effect=_emit_session_update)
        agent._emit_status = AsyncMock(side_effect=_emit_status)
        agent._prompt_loop = AsyncMock(side_effect=_prompt_loop)

        await agent.prompt(
            prompt=[TextContentBlock(type="text", text="hello world")],
            session_id="session-1",
        )

        assert call_order[:3] == [
            "user_message_chunk",
            "status:Preparing agent",
            "get_or_create_agent",
        ]
        agent._session_mgr.flush_session.assert_called_once_with("session-1")


class TestBootstrapWarmup:
    async def test_tui_bootstrap_warms_session_before_payload(self, agent):
        result = await agent._ext_tui_bootstrap({"session_id": "session-1", "cwd": "/work"})

        agent._session_mgr.warm_session.assert_called_once_with("session-1", cwd="/work")
        agent._session_mgr.get_bootstrap_payload.assert_called_once_with("session-1")
        assert result["models"] == ["openai:gpt-4o-mini"]


class TestExtractText:
    def test_string_content(self):
        assert MalibuAgent._extract_text("hello") == "hello"

    def test_list_of_text_blocks(self):
        content = [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}]
        assert MalibuAgent._extract_text(content) == "hello world"

    def test_list_with_strings(self):
        content = ["a", "b"]
        assert MalibuAgent._extract_text(content) == "ab"

    def test_mixed_list(self):
        content = [{"type": "text", "text": "hi"}, "there"]
        assert MalibuAgent._extract_text(content) == "hithere"

    def test_non_text_block_skipped(self):
        content = [{"type": "image", "url": "x"}, {"type": "text", "text": "hi"}]
        assert MalibuAgent._extract_text(content) == "hi"
