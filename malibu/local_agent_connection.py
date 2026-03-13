from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from acp import connect_to_agent
from acp.agent.connection import AgentSideConnection


class LocalAgentHandle:
    """Process-like wrapper for an in-process ACP agent task."""

    def __init__(self, task: asyncio.Task[None]) -> None:
        self._task = task
        self.stderr = None

    @property
    def returncode(self) -> int | None:
        if not self._task.done():
            return None
        if self._task.cancelled():
            return 0
        if self._task.exception() is not None:
            return 1
        return 0

    async def wait(self) -> int:
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        return self.returncode or 0

    def terminate(self) -> None:
        self._task.cancel()

    def kill(self) -> None:
        self._task.cancel()


@asynccontextmanager
async def connect_local_agent(
    client: Any,
    *,
    settings: Any,
) -> AsyncIterator[tuple[Any, LocalAgentHandle]]:
    """Connect a client to a MalibuAgent without spawning a subprocess."""
    from malibu.server.agent import MalibuAgent

    client_sock, agent_sock = socket.socketpair()
    client_sock.setblocking(False)
    agent_sock.setblocking(False)

    client_reader, client_writer = await asyncio.open_connection(sock=client_sock)
    agent_reader, agent_writer = await asyncio.open_connection(sock=agent_sock)

    agent = MalibuAgent(settings)
    agent_conn = AgentSideConnection(agent, agent_writer, agent_reader, listening=False)
    listen_task = asyncio.create_task(agent_conn.listen(), name="malibu.local_agent.listen")
    conn = connect_to_agent(client, client_writer, client_reader)
    handle = LocalAgentHandle(listen_task)

    try:
        yield conn, handle
    finally:
        await conn.close()
        agent_writer.close()
        client_writer.close()
        with contextlib.suppress(Exception):
            await agent_writer.wait_closed()
        with contextlib.suppress(Exception):
            await client_writer.wait_closed()
        listen_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listen_task
