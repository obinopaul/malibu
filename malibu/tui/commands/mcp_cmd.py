"""Built-in /mcp command — opens the MCP server viewer modal."""

from __future__ import annotations

from malibu.tui.commands.base import BaseCommand, CommandContext


class McpCommand(BaseCommand):
    name = "mcp"
    description = "Open the MCP server viewer."
    usage = "/mcp"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        from malibu.mcp.discovery import discover_mcp_servers
        from malibu.tui.widgets.mcp_viewer import McpViewerModal

        servers = discover_mcp_servers(ctx.app.cwd)
        server_data = [
            {
                "name": s.get("name", s.get("command", "<unnamed>")),
                "tools": s.get("tools", []),
            }
            for s in servers
        ]

        await ctx.app.push_screen_wait(McpViewerModal(server_data))
