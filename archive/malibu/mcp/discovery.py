"""MCP server discovery from project and user configuration files.

Reads MCP server definitions from two locations (higher precedence last):
  1. ``~/.malibu/mcp.json``   — user-level servers
  2. ``.malibu/mcp.json``     — project-level servers (relative to session cwd)

JSON schema::

    {
      "servers": [
        {
          "name": "my-server",
          "type": "stdio",
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem"]
        },
        {
          "name": "remote-server",
          "type": "sse",
          "url": "http://localhost:3000/sse"
        },
        {
          "name": "http-server",
          "type": "http",
          "url": "http://localhost:3000/mcp"
        }
      ]
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from malibu.telemetry.logging import get_logger

log = get_logger(__name__)

_USER_CONFIG = Path.home() / ".malibu" / "mcp.json"


def discover_mcp_servers(cwd: str | None = None) -> list[dict[str, Any]]:
    """Discover MCP server configurations from user and project config files.

    Returns a list of server config dicts.  Project-level servers override
    user-level servers with the same ``name``.
    """
    project_config = Path(cwd).resolve() / ".malibu" / "mcp.json" if cwd else None

    seen: dict[str, dict[str, Any]] = {}

    # User-level (lower precedence)
    _load_config_file(_USER_CONFIG, seen, "user")

    # Project-level (higher precedence)
    if project_config is not None:
        _load_config_file(project_config, seen, "project")

    servers = list(seen.values())
    log.info("mcp_servers_discovered", count=len(servers))
    return servers


def _load_config_file(
    path: Path, seen: dict[str, dict[str, Any]], level: str
) -> None:
    """Parse a single mcp.json file and merge its servers into *seen*."""
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("mcp_config_error", path=str(path), error=str(exc))
        return

    servers = data.get("servers", [])
    if not isinstance(servers, list):
        log.warning("mcp_config_bad_schema", path=str(path))
        return

    for entry in servers:
        name = entry.get("name")
        server_type = entry.get("type")
        if not name or not server_type:
            log.warning("mcp_config_missing_fields", entry=entry)
            continue

        seen[name] = {
            "name": name,
            "type": server_type,
            "command": entry.get("command"),
            "args": entry.get("args", []),
            "url": entry.get("url"),
            "level": level,
        }
        log.debug("mcp_server_found", name=name, type=server_type, level=level)


def build_server_configs(servers: list[dict[str, Any]]) -> list[Any]:
    """Convert raw server dicts into ACP MCP server config objects.

    Returns a list of ``McpServerStdio``, ``SseMcpServer``, or ``HttpMcpServer``
    instances depending on the ``type`` field.

    Imports are deferred so the module can be loaded even when
    ``agents`` / ``acp`` packages are not installed.
    """
    from acp.models.mcp import HttpMcpServer, McpServerStdio, SseMcpServer

    configs: list[Any] = []
    for srv in servers:
        server_type = srv["type"]
        name = srv["name"]
        try:
            if server_type == "stdio":
                configs.append(
                    McpServerStdio(
                        name=name,
                        command=srv["command"],
                        args=srv.get("args", []),
                    )
                )
            elif server_type == "sse":
                configs.append(
                    SseMcpServer(
                        name=name,
                        url=srv["url"],
                    )
                )
            elif server_type == "http":
                configs.append(
                    HttpMcpServer(
                        name=name,
                        url=srv["url"],
                    )
                )
            else:
                log.warning("mcp_unknown_type", name=name, type=server_type)
        except Exception:
            log.exception("mcp_config_build_error", name=name)

    return configs
