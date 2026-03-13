"""MCP-to-LangChain tool adapter.

Converts tools discovered on MCP servers into LangChain ``@tool``-decorated
functions that the agent graph can bind and execute.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool

from malibu.telemetry.logging import get_logger

log = get_logger(__name__)


def convert_mcp_tools(
    mcp_tools: list[dict[str, Any]],
    client: Any,
) -> list[StructuredTool]:
    """Convert a list of MCP tool definitions into LangChain tools.

    Args:
        mcp_tools: Tool metadata dicts with at least ``name`` and
            ``description`` keys.  An optional ``inputSchema`` key
            provides the JSON Schema for the tool's arguments.
        client: The MCP client instance used to execute tool calls.

    Returns:
        A list of ``StructuredTool`` instances that proxy calls through
        the MCP client.
    """
    tools: list[StructuredTool] = []
    for tool_def in mcp_tools:
        name = tool_def.get("name", "")
        description = tool_def.get("description", "")
        if not name:
            log.warning("mcp_tool_no_name", tool_def=tool_def)
            continue

        tool = _make_langchain_tool(name, description, client)
        tools.append(tool)
        log.debug("mcp_tool_converted", name=name)

    log.info("mcp_tools_converted", count=len(tools))
    return tools


def _make_langchain_tool(
    name: str,
    description: str,
    client: Any,
) -> StructuredTool:
    """Create a single LangChain ``StructuredTool`` that wraps an MCP tool call."""

    async def _invoke(**kwargs: Any) -> str:
        """Execute the MCP tool and return the result as a string."""
        try:
            result = await client.call_tool(name, kwargs)
            # Normalize result to string
            if isinstance(result, str):
                return result
            if isinstance(result, dict):
                return json.dumps(result, indent=2, default=str)
            return str(result)
        except Exception as exc:
            log.exception("mcp_tool_call_error", tool=name)
            return f"Error calling MCP tool {name!r}: {exc}"

    return StructuredTool.from_function(
        func=None,
        coroutine=_invoke,
        name=name,
        description=description or f"MCP tool: {name}",
    )
