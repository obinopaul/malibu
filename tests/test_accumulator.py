"""Tests for malibu.client.accumulator module."""

from __future__ import annotations

from acp.schema import AgentMessageChunk, TextContentBlock

from malibu.client.accumulator import MalibuSessionAccumulator


def _make_chunk(text: str) -> AgentMessageChunk:
    return AgentMessageChunk(
        content=TextContentBlock(type="text", text=text),
        session_update="agent_message_chunk",
    )


def test_process_and_snapshot():
    acc = MalibuSessionAccumulator()
    acc.process_update("sess-1", _make_chunk("Hello"))
    snap = acc.snapshot("sess-1")
    assert snap is not None


def test_clear_session():
    acc = MalibuSessionAccumulator()
    acc.process_update("sess-1", _make_chunk("data"))
    acc.clear("sess-1")
    assert acc.snapshot("sess-1") is None


def test_nonexistent_session_snapshot_is_none():
    acc = MalibuSessionAccumulator()
    assert acc.snapshot("doesnt-exist") is None
