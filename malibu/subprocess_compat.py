from __future__ import annotations

import asyncio
import contextlib
import os
import queue
import subprocess
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, BinaryIO, cast

from acp.client.connection import ClientSideConnection
from acp.interfaces import Agent, Client
from acp.transports import default_environment as acp_default_environment
from acp.transports import spawn_stdio_transport as acp_spawn_stdio_transport

PIPE = subprocess.PIPE
STDOUT = subprocess.STDOUT


def default_environment() -> dict[str, str]:
    """Mirror ACP's environment trimming for subprocess spawns."""
    return acp_default_environment()


class _ReaderPump:
    def __init__(self, stream: BinaryIO, loop: asyncio.AbstractEventLoop) -> None:
        self.reader = asyncio.StreamReader()
        self._stream = stream
        self._loop = loop
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            while True:
                data = self._stream.readline()
                if not data:
                    break
                self._loop.call_soon_threadsafe(self.reader.feed_data, data)
        except Exception as exc:
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self.reader.set_exception, exc)
        finally:
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self.reader.feed_eof)

    async def wait_closed(self) -> None:
        await asyncio.to_thread(self._thread.join, 1.0)


class _WritePipeProtocol(asyncio.BaseProtocol):
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._paused = False
        self._drain_waiter: asyncio.Future[None] | None = None
        self._close_waiter: asyncio.Future[None] = loop.create_future()

    def pause_writing(self) -> None:  # type: ignore[override]
        self._paused = True
        if self._drain_waiter is None:
            self._drain_waiter = self._loop.create_future()

    def resume_writing(self) -> None:  # type: ignore[override]
        self._paused = False
        if self._drain_waiter is not None and not self._drain_waiter.done():
            self._drain_waiter.set_result(None)
        self._drain_waiter = None

    def connection_lost(self, exc: Exception | None) -> None:  # type: ignore[override]
        if self._drain_waiter is not None and not self._drain_waiter.done():
            if exc is None:
                self._drain_waiter.set_result(None)
            else:
                self._drain_waiter.set_exception(exc)
        if not self._close_waiter.done():
            if exc is None:
                self._close_waiter.set_result(None)
            else:
                self._close_waiter.set_exception(exc)

    async def _drain_helper(self) -> None:
        if self._paused and self._drain_waiter is not None:
            await self._drain_waiter

    def _get_close_waiter(self, _stream: object) -> asyncio.Future[None]:
        return self._close_waiter


class _ThreadedWriteTransport(asyncio.WriteTransport):
    def __init__(self, stream: BinaryIO, loop: asyncio.AbstractEventLoop, protocol: _WritePipeProtocol) -> None:
        self._stream = stream
        self._loop = loop
        self._protocol = protocol
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._closing = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def write(self, data: bytes) -> None:  # type: ignore[override]
        if self._closing:
            return
        self._protocol.pause_writing()
        self._queue.put(data)

    def can_write_eof(self) -> bool:  # type: ignore[override]
        return False

    def is_closing(self) -> bool:  # type: ignore[override]
        return self._closing

    def close(self) -> None:  # type: ignore[override]
        if self._closing:
            return
        self._closing = True
        self._queue.put(None)

    def abort(self) -> None:  # type: ignore[override]
        self.close()

    def get_extra_info(self, name: str, default=None):  # type: ignore[override]
        return default

    async def wait_closed(self) -> None:
        await asyncio.to_thread(self._thread.join, 1.0)

    def _run(self) -> None:
        exc: Exception | None = None
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                self._stream.write(item)
                self._stream.flush()
                with contextlib.suppress(RuntimeError):
                    self._loop.call_soon_threadsafe(self._protocol.resume_writing)
        except Exception as err:
            exc = err
        finally:
            with contextlib.suppress(Exception):
                self._stream.close()
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._protocol.connection_lost, exc)


class CompatProcess:
    """Async-friendly wrapper around subprocess.Popen."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        stdin: asyncio.StreamWriter | None,
        stdout: asyncio.StreamReader | None,
        stderr: asyncio.StreamReader | None,
        reader_pumps: list[_ReaderPump],
        stdin_transport: _ThreadedWriteTransport | None,
    ) -> None:
        self._process = process
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self._reader_pumps = reader_pumps
        self._stdin_transport = stdin_transport

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    async def wait(self) -> int:
        return await asyncio.to_thread(self._process.wait)

    async def communicate(self, input: bytes | None = None) -> tuple[bytes | None, bytes | None]:
        if input is not None and self.stdin is not None:
            self.stdin.write(input)
            await self.stdin.drain()
        if self.stdin is not None:
            self.stdin.close()
        if self._stdin_transport is not None:
            await self._stdin_transport.wait_closed()

        stdout_task = asyncio.create_task(self.stdout.read()) if self.stdout is not None else None
        stderr_task = asyncio.create_task(self.stderr.read()) if self.stderr is not None else None

        await self.wait()

        stdout = await stdout_task if stdout_task is not None else None
        stderr = await stderr_task if stderr_task is not None else None
        return stdout, stderr

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()

    async def wait_readers_closed(self) -> None:
        for pump in self._reader_pumps:
            await pump.wait_closed()


async def create_subprocess_exec(
    *args: str,
    stdin: int | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> asyncio.subprocess.Process | CompatProcess:
    """Spawn a subprocess, falling back to blocking pipes on Windows.

    Python 3.12's asyncio subprocess transport can fail with WinError 5 when it
    creates named pipes on some Windows environments. Standard Popen pipes do
    not have that problem, so Windows uses a thread-backed compatibility layer.
    """
    if os.name != "nt":
        return await asyncio.create_subprocess_exec(
            *args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            **kwargs,
        )

    popen = subprocess.Popen(
        list(args),
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        bufsize=0,
    )

    loop = asyncio.get_running_loop()
    pumps: list[_ReaderPump] = []

    stdin_writer = None
    stdin_transport = None
    if popen.stdin is not None:
        protocol = _WritePipeProtocol(loop)
        stdin_transport = _ThreadedWriteTransport(popen.stdin, loop, protocol)
        stdin_writer = asyncio.StreamWriter(cast(asyncio.Transport, stdin_transport), protocol, None, loop)

    stdout_reader = None
    if popen.stdout is not None:
        stdout_pump = _ReaderPump(popen.stdout, loop)
        stdout_reader = stdout_pump.reader
        pumps.append(stdout_pump)

    stderr_reader = None
    if popen.stderr is not None:
        stderr_pump = _ReaderPump(popen.stderr, loop)
        stderr_reader = stderr_pump.reader
        pumps.append(stderr_pump)

    return CompatProcess(
        popen,
        stdin=stdin_writer,
        stdout=stdout_reader,
        stderr=stderr_reader,
        reader_pumps=pumps,
        stdin_transport=stdin_transport,
    )


@asynccontextmanager
async def spawn_stdio_transport(
    command: str,
    *args: str,
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
    stderr: int | None = PIPE,
    limit: int | None = None,
    shutdown_timeout: float = 2.0,
) -> AsyncIterator[tuple[asyncio.StreamReader, Any, asyncio.subprocess.Process | CompatProcess]]:
    """Launch a subprocess and expose stdio streams for ACP connections."""
    if os.name != "nt":
        async with acp_spawn_stdio_transport(
            command,
            *args,
            env=env,
            cwd=cwd,
            stderr=stderr,
            limit=limit,
            shutdown_timeout=shutdown_timeout,
        ) as result:
            yield result
        return

    merged_env = dict(default_environment())
    if env:
        merged_env.update(env)

    process = await create_subprocess_exec(
        command,
        *args,
        stdin=PIPE,
        stdout=PIPE,
        stderr=stderr,
        cwd=cwd,
        env=merged_env,
    )

    if process.stdout is None or process.stdin is None:
        process.kill()
        await process.wait()
        raise RuntimeError("spawn_stdio_transport requires stdout/stdin pipes")

    try:
        yield process.stdout, process.stdin, process
    finally:
        process.stdin.close()
        if isinstance(process, CompatProcess) and process._stdin_transport is not None:
            with contextlib.suppress(Exception):
                await process._stdin_transport.wait_closed()

        try:
            await asyncio.wait_for(process.wait(), timeout=shutdown_timeout)
        except asyncio.TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=shutdown_timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

        if isinstance(process, CompatProcess):
            await process.wait_readers_closed()


@asynccontextmanager
async def spawn_agent_process(
    to_client: Callable[[Agent], Client] | Client,
    command: str,
    *args: str,
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
    transport_kwargs: Mapping[str, Any] | None = None,
    **connection_kwargs: Any,
) -> AsyncIterator[tuple[ClientSideConnection, asyncio.subprocess.Process | CompatProcess]]:
    """Spawn an ACP agent subprocess with Windows-safe stdio transport."""
    async with spawn_stdio_transport(
        command,
        *args,
        env=env,
        cwd=cwd,
        **(dict(transport_kwargs) if transport_kwargs else {}),
    ) as (reader, writer, process):
        conn = ClientSideConnection(to_client, writer, reader, **connection_kwargs)
        try:
            yield conn, process
        finally:
            await conn.close()
