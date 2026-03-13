"""Built-in /mode command."""

from __future__ import annotations

from malibu.tui.commands.base import BaseCommand, CommandContext

MODE_MAP: dict[str, str] = {
    "plan": "plan",
    "normal": "accept_edits",
    "auto": "accept_everything",
}


class ModeCommand(BaseCommand):
    name = "mode"
    description = "Switch the agent mode (plan, normal, auto)."
    usage = "/mode [plan|normal|auto]"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        if not args:
            self._post_system(
                ctx,
                "[bold]Available modes:[/]\n"
                "  plan   - All tools require approval\n"
                "  normal - Auto-accept edits\n"
                "  auto   - Accept everything",
            )
            return

        mode_name = args[0].lower()
        mode_id = MODE_MAP.get(mode_name)

        if mode_id is None:
            self._post_system(
                ctx,
                f"[bold red]Unknown mode:[/] {mode_name}. "
                f"Choose from: {', '.join(MODE_MAP)}",
            )
            return

        await ctx.conn.set_session_mode(
            session_id=ctx.session_id, mode_id=mode_id
        )
        self._post_system(ctx, f"Mode set to [bold]{mode_name}[/] ({mode_id})")

    @staticmethod
    def _post_system(ctx: CommandContext, text: str) -> None:
        from acp.schema import AgentMessageChunk, TextContentBlock
        from malibu.tui.bridge import SessionUpdateMessage

        update = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text=text),
        )
        ctx.app.post_message(SessionUpdateMessage(ctx.session_id, update))
