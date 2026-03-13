"""MCP connection lifecycle management.

Tracks connections to MCP servers, allowing the agent to connect,
disconnect, and list active server connections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from malibu.telemetry.logging import get_logger

log = get_logger(__name__)


class ConnectionStatus(Enum):
    """Status of a single MCP server connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class ConnectionInfo:
    """Metadata for a single MCP server connection."""

    name: str
    server_type: str
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    tools: list[str] = field(default_factory=list)
    error: str | None = None


class McpConnectionManager:
    """Manages connections to MCP servers."""

    def __init__(self) -> None:
        self._connections: dict[str, ConnectionInfo] = {}
        self._clients: dict[str, Any] = {}

    async def connect(self, server_config: dict[str, Any]) -> ConnectionInfo:
        """Establish a connection to an MCP server.

        Args:
            server_config: Server configuration dict with ``name``, ``type``,
                and connection parameters (``command``/``args`` or ``url``).

        Returns:
            The updated ``ConnectionInfo`` for this server.
        """
        name = server_config["name"]
        server_type = server_config.get("type", "unknown")
        info = ConnectionInfo(name=name, server_type=server_type)
        self._connections[name] = info

        info.status = ConnectionStatus.CONNECTING
        log.info("mcp_connecting", name=name, type=server_type)

        try:
            client = await self._create_client(server_config)
            self._clients[name] = client

            # Discover tools exposed by the server
            tools = await self._list_server_tools(client)
            info.tools = [t.get("name", "") for t in tools] if tools else []
            info.status = ConnectionStatus.CONNECTED
            log.info("mcp_connected", name=name, tool_count=len(info.tools))
        except Exception as exc:
            info.status = ConnectionStatus.ERROR
            info.error = str(exc)
            log.exception("mcp_connect_error", name=name)

        return info

    async def disconnect(self, server_name: str) -> None:
        """Close the connection to an MCP server.

        Args:
            server_name: The ``name`` of the server to disconnect.
        """
        client = self._clients.pop(server_name, None)
        if client is not None:
            try:
                if hasattr(client, "close"):
                    await client.close()
                elif hasattr(client, "aclose"):
                    await client.aclose()
            except Exception:
                log.exception("mcp_disconnect_error", name=server_name)

        info = self._connections.get(server_name)
        if info is not None:
            info.status = ConnectionStatus.DISCONNECTED
            info.tools = []
            info.error = None
        log.info("mcp_disconnected", name=server_name)

    def list_connected(self) -> list[dict[str, Any]]:
        """Return information about all tracked server connections."""
        return [
            {
                "name": info.name,
                "type": info.server_type,
                "status": info.status.value,
                "tools": info.tools,
                "error": info.error,
            }
            for info in self._connections.values()
        ]

    def get_client(self, server_name: str) -> Any | None:
        """Return the raw MCP client for a connected server, or ``None``."""
        return self._clients.get(server_name)

    # ── internals ─────────────────────────────────────────────────

    async def _create_client(self, server_config: dict[str, Any]) -> Any:
        """Instantiate the appropriate MCP client for *server_config*.

        Imports are deferred so the module loads even when MCP packages
        are not installed.
        """
        server_type = server_config.get("type", "stdio")

        if server_type == "stdio":
            from acp.mcp.client.stdio import StdioMcpClient

            client = StdioMcpClient(
                command=server_config["command"],
                args=server_config.get("args", []),
            )
            await client.connect()
            return client

        elif server_type in ("sse", "http"):
            from acp.mcp.client.http import HttpMcpClient

            client = HttpMcpClient(url=server_config["url"])
            await client.connect()
            return client

        raise ValueError(f"Unsupported MCP server type: {server_type!r}")

    async def _list_server_tools(self, client: Any) -> list[dict[str, Any]]:
        """Query an MCP client for its available tools."""
        if hasattr(client, "list_tools"):
            result = await client.list_tools()
            # Normalize: result may be a list of dicts or tool objects
            if isinstance(result, list):
                return [
                    t if isinstance(t, dict) else {"name": getattr(t, "name", ""), "description": getattr(t, "description", "")}
                    for t in result
                ]
        return []
