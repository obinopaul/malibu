from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from acp import PROTOCOL_VERSION, text_block

from malibu.client.client import MalibuClient
from malibu.config import get_settings
from malibu.local_agent_connection import connect_local_agent


@pytest.mark.asyncio
async def test_connect_local_agent_can_create_session(tmp_path) -> None:
    settings = get_settings()
    client = MalibuClient(settings, cwd=str(tmp_path))

    async with connect_local_agent(client, settings=settings) as (conn, process):
        response = await conn.initialize(protocol_version=PROTOCOL_VERSION, client_capabilities=None)
        session = await conn.new_session(cwd=str(tmp_path), mcp_servers=[])

    await client.cleanup()

    assert response.protocol_version == PROTOCOL_VERSION
    assert session.session_id
    assert process.returncode == 0


class _FakePromptGraph:
    async def astream(self, input_data, config, stream_mode, subgraphs):  # noqa: ANN001, ARG002
        yield ((), "messages", ("hello from fake agent", {}))

    async def aget_state(self, config):  # noqa: ANN001, ARG002
        return SimpleNamespace(interrupts=[], next=[])


@pytest.mark.asyncio
async def test_connect_local_agent_prompt_streams_first_response(tmp_path) -> None:
    settings = get_settings()
    seen: list[tuple[str, str]] = []

    async def display_handler(session_id: str, update: object, **kwargs: object) -> None:  # noqa: ARG001
        update_type = getattr(update, "session_update", type(update).__name__)
        content = getattr(update, "content", None)
        text = getattr(content, "text", "") if content is not None else ""
        seen.append((str(update_type), str(text)))

    client = MalibuClient(
        settings,
        cwd=str(tmp_path),
        display_handler=display_handler,
    )
    fake_graph = _FakePromptGraph()

    with patch("malibu.server.agent.SessionManager") as MockSessionMgr:
        session_mgr = MockSessionMgr.return_value
        session_mgr.create_session = MagicMock(return_value=fake_graph)
        session_mgr.get_agent = MagicMock(return_value=fake_graph)
        session_mgr.get_or_create_agent = MagicMock(return_value=fake_graph)
        session_mgr.get_cwd = MagicMock(return_value=str(tmp_path))
        session_mgr.get_callbacks = MagicMock(return_value=[])
        session_mgr.record_session_update = MagicMock()
        session_mgr.record_tui_event = MagicMock()
        session_mgr.get_bootstrap_payload = MagicMock(return_value={"session_title": "Session deadbeef"})

        async with connect_local_agent(client, settings=settings) as (conn, process):
            await conn.initialize(protocol_version=PROTOCOL_VERSION, client_capabilities=None)
            session = await conn.new_session(cwd=str(tmp_path), mcp_servers=[])
            response = await asyncio.wait_for(
                conn.prompt(session_id=session.session_id, prompt=[text_block("hello")]),
                timeout=5.0,
            )

    await client.cleanup()

    assert response.stop_reason == "end_turn"
    assert ("user_message_chunk", "hello") in seen
    assert ("agent_message_chunk", "hello from fake agent") in seen
    assert process.returncode == 0


@pytest.mark.asyncio
async def test_connect_local_agent_bootstrap_survives_large_saved_sessions(tmp_path) -> None:
    settings = get_settings()
    client = MalibuClient(settings, cwd=str(tmp_path))
    session_dir = tmp_path / ".malibu" / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    large_history = [
        {
            "kind": "session_update",
            "payload": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": f"chunk-{index}-" + ("x" * 900)},
            },
        }
        for index in range(120)
    ]
    oversized_record = {
        "session_id": "older-session",
        "cwd": str(tmp_path),
        "title": "Older Session",
        "mode": "accept_edits",
        "model": "openai:gpt-4o-mini",
        "config": {},
        "history": large_history,
        "created_at": "2026-03-14T00:00:00+00:00",
        "updated_at": "2026-03-14T00:00:00+00:00",
    }
    (session_dir / "older-session.json").write_text(
        json.dumps(oversized_record, ensure_ascii=True),
        encoding="utf-8",
    )

    async with connect_local_agent(client, settings=settings) as (conn, process):
        await conn.initialize(protocol_version=PROTOCOL_VERSION, client_capabilities=None)
        session = await conn.new_session(cwd=str(tmp_path), mcp_servers=[])
        payload = await asyncio.wait_for(
            conn.ext_method(
                "tui_bootstrap",
                {"session_id": session.session_id, "cwd": str(tmp_path)},
            ),
            timeout=5.0,
        )
        response = await asyncio.wait_for(
            conn.prompt(session_id=session.session_id, prompt=[text_block("hello")]),
            timeout=20.0,
        )

    await client.cleanup()

    assert payload["models"] == ["openai:gpt-4o-mini"]
    assert payload["sessions"]
    assert "history" not in payload["sessions"][0]
    assert response.stop_reason == "end_turn"
    assert process.returncode == 0
