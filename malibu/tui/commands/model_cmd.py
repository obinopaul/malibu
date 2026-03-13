"""Built-in /model command."""

from __future__ import annotations

from malibu.tui.commands.base import BaseCommand, CommandContext


class ModelCommand(BaseCommand):
    name = "model"
    description = "Show or change the active model."
    usage = "/model [model_id]"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        if not args:
            self._post_system(
                ctx,
                "Use [bold]/model <model_id>[/] to switch the active model.",
            )
            return

        model_id = args[0]
        await ctx.conn.set_session_model(
            session_id=ctx.session_id, model_id=model_id
        )
        self._post_system(ctx, f"[dim]Model set to [bold]{model_id}[/][/]")

    @staticmethod
    def _post_system(ctx: CommandContext, text: str) -> None:
        from acp.schema import AgentMessageChunk, TextContentBlock
        from malibu.tui.bridge import SessionUpdateMessage

        update = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text=text),
        )
        ctx.app.post_message(SessionUpdateMessage(ctx.session_id, update))
