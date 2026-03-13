"""Built-in /mode command."""

from __future__ import annotations

from malibu.agent.modes import DEFAULT_MODES
from malibu.tui.commands.base import BaseCommand, CommandContext

MODE_MAP: dict[str, str] = {
    "plan": "plan",
    "ask": "ask_before_edits",
    "normal": "accept_edits",
    "auto": "accept_everything",
    "ask_before_edits": "ask_before_edits",
    "accept_edits": "accept_edits",
    "accept_everything": "accept_everything",
}


class ModeCommand(BaseCommand):
    name = "mode"
    description = "Switch the agent mode."
    usage = "/mode [plan|ask_before_edits|accept_edits|accept_everything]"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        if not args:
            mode_lines = "\n".join(
                f"  - **{mode.id:18}** {mode.description}"
                for mode in DEFAULT_MODES.available_modes
            )
            self._post_system(
                ctx,
                "**Available modes:**\n\n"
                f"{mode_lines}\n\n"
                "*Aliases: normal -> accept_edits, auto -> accept_everything, ask -> ask_before_edits*",
            )
            return

        mode_name = args[0].lower()
        mode_id = MODE_MAP.get(mode_name)

        if mode_id is None:
            self._post_system(
                ctx,
                f"**Unknown mode:** `{mode_name}`. "
                f"Choose from: {', '.join(mode.id for mode in DEFAULT_MODES.available_modes)}",
            )
            return
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
