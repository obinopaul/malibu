"""Built-in /model command."""

from __future__ import annotations

from malibu.tui.commands.base import BaseCommand, CommandContext
from malibu.tui.screens import OptionPickerItem, OptionPickerScreen


class ModelCommand(BaseCommand):
    name = "model"
    description = "Show or change the active model."
    usage = "/model [model_id]"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        if not args:
            model_candidates = list(ctx.app.get_model_candidates())
            if not model_candidates:
                self._post_system(
                    ctx,
                    "No model choices are currently available in the TUI bootstrap state.",
                )
                return
            selected = await ctx.app.push_screen_wait(
                OptionPickerScreen(
                    title="Switch Model",
                    subtitle="Select the active language model for this session.",
                    items=[
                        OptionPickerItem(
                            value=model,
                            label=model,
                            description="available model",
                        )
                        for model in model_candidates
                    ],
                )
            )
            if not selected:
                return
            model_id = selected
        else:
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
