from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from malibu.config import Settings
from malibu.server.agent import MalibuAgent
from malibu.tui.protocol import TUI_INTERRUPT_METHOD


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///test.db",
        jwt_secret="test-secret-key-for-tests-only",
        llm_model="openai:gpt-4o-mini",
        llm_api_key="sk-test-key",
        allowed_paths=["."],
        log_level="DEBUG",
    )


@pytest.fixture
def agent(settings: Settings) -> MalibuAgent:
    with patch("malibu.server.agent.SessionManager") as MockSessionMgr:
        session_mgr = MockSessionMgr.return_value
        session_mgr.get_cwd.return_value = "."
        session_mgr.get_bootstrap_payload.return_value = {"session_title": "Session deadbeef"}
        session_mgr.record_session_update = MagicMock()
        session_mgr.record_tui_event = MagicMock()
        a = MalibuAgent(settings)
        a._conn = MagicMock()
        a._conn.ext_method = AsyncMock()
        a._conn.ext_notification = AsyncMock()
        a._conn.session_update = AsyncMock()
        return a


async def test_handle_interrupts_uses_tui_interrupt_for_tool_approval(agent: MalibuAgent) -> None:
    agent._conn.ext_method.return_value = {"decision": {"type": "approve"}}
    current_state = SimpleNamespace(
        next=True,
        interrupts=[
            SimpleNamespace(
                id="interrupt-1",
                value={
                    "action_requests": [{"name": "execute", "args": {"command": "dir"}}],
                    "review_configs": [{"allowed_decisions": ["approve", "edit", "reject"]}],
                },
            )
        ],
    )

    result = await agent._handle_interrupts(current_state=current_state, session_id="sess-1")

    assert result == {"decisions": [{"type": "approve"}]}
    agent._conn.ext_method.assert_awaited_once()
    assert agent._conn.ext_method.await_args.args[0] == TUI_INTERRUPT_METHOD


async def test_handle_interrupts_returns_ask_user_resume_payload(agent: MalibuAgent) -> None:
    agent._conn.ext_method.return_value = {"status": "answered", "answers": ["yes"]}
    current_state = SimpleNamespace(
        next=True,
        interrupts=[
            SimpleNamespace(
                id="interrupt-2",
                value={
                    "type": "ask_user",
                    "questions": [{"question": "Continue?", "type": "text"}],
                    "tool_call_id": "tool-1",
                },
            )
        ],
    )

    result = await agent._handle_interrupts(current_state=current_state, session_id="sess-1")

    assert result == {"status": "answered", "answers": ["yes"]}
    agent._conn.ext_method.assert_awaited_once()
