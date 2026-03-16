"""Terminal management for the ACP client.

Implements all 5 terminal-related client methods:
  create_terminal, terminal_output, release_terminal,
  wait_for_terminal_exit, kill_terminal
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from acp.schema import (
    CreateTerminalResponse,
    EnvVariable,
    KillTerminalCommandResponse,
    ReleaseTerminalResponse,
    TerminalOutputResponse,
)

from malibu.telemetry.logging import get_logger
from malibu.subprocess_compat import create_subprocess_exec

log = get_logger(__name__)


@dataclass
class TerminalExitResult:
    """Result of waiting for terminal exit — includes output for convenience."""

    exit_code: int
    output: str


class _Terminal:
    """Wrapper around an async subprocess representing a terminal session."""

    __slots__ = ("terminal_id", "process", "output_buffer", "cwd", "_output_limit", "_truncated")

    def __init__(
        self,
        terminal_id: str,
        process: Any,
        cwd: str,
        output_limit: int | None,
    ) -> None:
        self.terminal_id = terminal_id
        self.process = process
        self.output_buffer: list[str] = []
        self.cwd = cwd
        self._output_limit = output_limit
        self._truncated = False

    async def collect_output(self) -> None:
        """Background task to collect stdout/stderr into the output buffer."""
        assert self.process.stdout is not None
        while True:
            line = await self.process.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace")
            self.output_buffer.append(decoded)
            if self._output_limit and sum(len(l.encode()) for l in self.output_buffer) > self._output_limit:
                self.output_buffer = self.output_buffer[-100:]  # keep last 100 lines
                self._truncated = True


class TerminalManager:
    """Manages terminal lifecycle for ACP client-side operations."""

    def __init__(self, *, cwd: str) -> None:
        self._cwd = cwd
        self._terminals: dict[str, _Terminal] = {}
        self._collectors: dict[str, asyncio.Task] = {}
        self._counter = 0

    async def create_terminal(
        self,
        command: str,
        *,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: list[EnvVariable] | None = None,
        output_byte_limit: int | None = None,
    ) -> CreateTerminalResponse:
        """Spawn a subprocess terminal."""
        self._counter += 1
        terminal_id = f"term-{self._counter}"

        cmd_parts = [command] + (args or [])
        work_dir = cwd or self._cwd

        proc_env = os.environ.copy()
        if env:
            for ev in env:
                proc_env[ev.name] = ev.value

        process = await create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=work_dir,
            env=proc_env,
        )

        terminal = _Terminal(terminal_id, process, work_dir, output_byte_limit)
        self._terminals[terminal_id] = terminal
        self._collectors[terminal_id] = asyncio.create_task(terminal.collect_output())

        log.info("terminal_created", terminal_id=terminal_id, command=command, cwd=work_dir)
        return CreateTerminalResponse(terminal_id=terminal_id)

    async def terminal_output(self, terminal_id: str) -> TerminalOutputResponse:
        """Get the current output from a terminal."""
        terminal = self._terminals.get(terminal_id)
        if terminal is None:
            raise ValueError(f"Terminal {terminal_id} not found")
        output = "".join(terminal.output_buffer)
        return TerminalOutputResponse(output=output, truncated=terminal._truncated)

    async def release_terminal(self, terminal_id: str) -> ReleaseTerminalResponse | None:
        """Release (detach from) a terminal without killing it."""
        terminal = self._terminals.pop(terminal_id, None)
        if terminal is None:
            return None
        collector = self._collectors.pop(terminal_id, None)
        if collector:
            collector.cancel()
        log.info("terminal_released", terminal_id=terminal_id)
        return ReleaseTerminalResponse()

    async def wait_for_terminal_exit(self, terminal_id: str) -> TerminalExitResult:
        """Block until a terminal process exits."""
        terminal = self._terminals.get(terminal_id)
        if terminal is None:
            raise ValueError(f"Terminal {terminal_id} not found")
        exit_code = await terminal.process.wait()

        # Ensure collector completes
        collector = self._collectors.get(terminal_id)
        if collector:
            await collector

        output = "".join(terminal.output_buffer)
        log.info("terminal_exited", terminal_id=terminal_id, exit_code=exit_code)
        return TerminalExitResult(exit_code=exit_code, output=output)

    async def kill_terminal(self, terminal_id: str) -> KillTerminalCommandResponse | None:
        """Kill a terminal process."""
        terminal = self._terminals.pop(terminal_id, None)
        if terminal is None:
            return None
        terminal.process.kill()
        collector = self._collectors.pop(terminal_id, None)
        if collector:
            collector.cancel()
        log.info("terminal_killed", terminal_id=terminal_id)
        return KillTerminalCommandResponse()

    async def cleanup(self) -> None:
        """Kill all remaining terminals on shutdown."""
        for tid in list(self._terminals.keys()):
            await self.kill_terminal(tid)
