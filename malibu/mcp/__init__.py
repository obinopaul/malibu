"""Malibu MCP (Model Context Protocol) integration.

Public API::

    from malibu.mcp import discover_mcp_servers, McpConnectionManager, convert_mcp_tools
"""

from malibu.mcp.connection import McpConnectionManager
from malibu.mcp.discovery import discover_mcp_servers
from malibu.mcp.tool_adapter import convert_mcp_tools

__all__ = ["McpConnectionManager", "convert_mcp_tools", "discover_mcp_servers"]
