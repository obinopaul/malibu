"""Built-in /compact command — triggers context compaction."""

from __future__ import annotations

from malibu.tui.commands.base import BaseCommand, CommandContext


class CompactCommand(BaseCommand):
    name = "compact"
    description = "Compact the current context window."
    usage = "/compact"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        self._post_system(ctx, "[dim]Compacting context...[/]")

        try:
            result = await ctx.conn.ext_method(
                "compact", {"session_id": ctx.session_id}
            )
            summary = result.get("summary", "Context compacted successfully.")
            self._post_system(
                ctx,
                f"[green]Compaction complete.[/]\n[dim]{summary}[/]",
            )
        except Exception as exc:
            self._post_system(ctx, f"[red]Compaction failed:[/] {exc}")

    @staticmethod
    def _post_system(ctx: CommandContext, text: str) -> None:
        from acp.schema import AgentMessageChunk, TextContentBlock
        from malibu.tui.bridge import SessionUpdateMessage

        update = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text=text),
        )
        ctx.app.post_message(SessionUpdateMessage(ctx.session_id, update))
