"""Built-in /config command."""

from __future__ import annotations

from malibu.tui.commands.base import BaseCommand, CommandContext


class ConfigCommand(BaseCommand):
    name = "config"
    description = "View or set a configuration option."
    usage = "/config [key] [value]"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        if len(args) < 2:
            self._post_system(
                ctx,
                "Use [bold]/config <key> <value>[/] to set a configuration option.",
            )
            return

        # Set a key
        key, value = args[0], args[1]
        await ctx.conn.set_config_option(
            session_id=ctx.session_id, key=key, value=value
        )
        self._post_system(
            ctx, f"[dim]Config [bold]{key}[/] set to {value!r}[/]"
        )

    @staticmethod
    def _post_system(ctx: CommandContext, text: str) -> None:
        from acp.schema import AgentMessageChunk, TextContentBlock
        from malibu.tui.bridge import SessionUpdateMessage

        update = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text=text),
        )
        ctx.app.post_message(SessionUpdateMessage(ctx.session_id, update))
