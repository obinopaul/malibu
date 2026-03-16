"""Built-in /clear command."""

from __future__ import annotations

from malibu.tui.commands.base import BaseCommand, CommandContext


class ClearCommand(BaseCommand):
    name = "clear"
    description = "Clear the message history. Use --new to start a fresh session."
    usage = "/clear [--new]"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        ctx.app.chat_screen.action_clear_messages()

        if "--new" in args:
            await ctx.app.new_session()
            if ctx.app.session_id:
                self._post_system(ctx, f"[dim]Started new session {ctx.app.session_id}[/]")

    @staticmethod
    def _post_system(ctx: CommandContext, text: str) -> None:
        from acp.schema import AgentMessageChunk, TextContentBlock
        from malibu.tui.bridge import SessionUpdateMessage

        update = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text=text),
        )
        ctx.app.post_message(SessionUpdateMessage(ctx.session_id, update))
