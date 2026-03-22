"""Tests for malibu.client.terminal_mgr module."""

from __future__ import annotations

import sys

import pytest

from malibu.client.terminal_mgr import TerminalManager


@pytest.fixture
def terminal_mgr(tmp_path) -> TerminalManager:
    return TerminalManager(cwd=str(tmp_path))


@pytest.mark.asyncio
async def test_create_and_wait(terminal_mgr):
    result = await terminal_mgr.create_terminal(
        sys.executable, args=["-c", "print('hello')"]
    )
    assert result.terminal_id.startswith("term-")
    exit_result = await terminal_mgr.wait_for_terminal_exit(result.terminal_id)
    assert exit_result.exit_code == 0
    assert "hello" in exit_result.output


@pytest.mark.asyncio
async def test_terminal_output(terminal_mgr):
    result = await terminal_mgr.create_terminal(
        sys.executable, args=["-c", "import time; print('foo'); time.sleep(0.2); print('bar')"]
    )
    # Wait for completion to ensure all output is captured
    exit_result = await terminal_mgr.wait_for_terminal_exit(result.terminal_id)
    assert "foo" in exit_result.output
    assert "bar" in exit_result.output


@pytest.mark.asyncio
async def test_kill_terminal(terminal_mgr):
    result = await terminal_mgr.create_terminal(
        sys.executable, args=["-c", "import time; time.sleep(60)"]
    )
    kill_result = await terminal_mgr.kill_terminal(result.terminal_id)
    assert kill_result is not None


@pytest.mark.asyncio
async def test_release_terminal(terminal_mgr):
    result = await terminal_mgr.create_terminal(
        sys.executable, args=["-c", "import time; time.sleep(60)"]
    )
    release_result = await terminal_mgr.release_terminal(result.terminal_id)
    assert release_result is not None
    # Terminal should no longer be tracked
    with pytest.raises(ValueError, match="not found"):
        await terminal_mgr.terminal_output(result.terminal_id)


@pytest.mark.asyncio
async def test_cleanup_kills_all(terminal_mgr):
    await terminal_mgr.create_terminal(sys.executable, args=["-c", "import time; time.sleep(60)"])
    await terminal_mgr.create_terminal(sys.executable, args=["-c", "import time; time.sleep(60)"])
    await terminal_mgr.cleanup()
    # No terminals should remain
    assert len(terminal_mgr._terminals) == 0


@pytest.mark.asyncio
async def test_truncation_flag_set_when_buffer_trimmed(tmp_path):
    """When output exceeds the byte limit, truncated should be True."""
    mgr = TerminalManager(cwd=str(tmp_path))
    # Generate output that exceeds 200 bytes limit
    script = "for i in range(500): print(f'line {i} ' + 'x' * 50)"
    result = await mgr.create_terminal(
        sys.executable, args=["-c", script], output_byte_limit=200
    )
    await mgr.wait_for_terminal_exit(result.terminal_id)
    output_resp = await mgr.terminal_output(result.terminal_id)
    assert output_resp.truncated is True


@pytest.mark.asyncio
async def test_truncation_flag_false_when_under_limit(tmp_path):
    """When output is under the byte limit, truncated should be False."""
    mgr = TerminalManager(cwd=str(tmp_path))
    result = await mgr.create_terminal(
        sys.executable, args=["-c", "print('hello')"], output_byte_limit=10000
    )
    await mgr.wait_for_terminal_exit(result.terminal_id)
    output_resp = await mgr.terminal_output(result.terminal_id)
    assert output_resp.truncated is False
