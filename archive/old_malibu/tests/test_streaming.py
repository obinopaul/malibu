"""Tests for malibu.server.streaming module."""

from __future__ import annotations

from malibu.server.streaming import ToolCallAccumulator, create_tool_call_start, format_execute_result


def test_accumulator_process_complete_call():
    acc = ToolCallAccumulator()

    # Simulate a message chunk with tool_call_chunks attribute (like LangChain AI chunks)
    class FakeMessageChunk:
        tool_call_chunks = [
            {"id": "call_001", "name": "read_file", "args": '{"path": "/tmp/test.txt"}', "index": 0},
        ]

    starts = acc.process_chunk(FakeMessageChunk())
    assert len(starts) == 1
    assert starts[0].tool_call_id == "call_001"


def test_accumulator_ignores_text_chunks():
    acc = ToolCallAccumulator()
    # String chunks should be ignored
    result = acc.process_chunk("just text")
    assert result == []


def test_create_tool_call_start_execute():
    start = create_tool_call_start(
        "call_001", "execute", {"command": "ls", "cwd": "/tmp"},
    )
    assert start.tool_call_id == "call_001"
    assert start.kind == "execute"
    assert start.title is not None


def test_create_tool_call_start_read():
    start = create_tool_call_start("call_002", "read_file", {"file_path": "/tmp/test.txt"})
    assert start.kind == "read"
    assert "test.txt" in start.title


def test_format_execute_result():
    result = format_execute_result("ls -la", "total 0\ndrwxr-xr-x 2 user user 40 Jan 1 00:00 .\n")
    assert "ls -la" in result
    assert "total 0" in result
