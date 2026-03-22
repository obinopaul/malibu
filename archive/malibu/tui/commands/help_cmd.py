"""Built-in /help command."""

from __future__ import annotations

from malibu.tui.commands.base import BaseCommand, CommandContext


class HelpCommand(BaseCommand):
    name = "help"
    description = "Show available commands or details for a specific command."
    usage = "/help [command]"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        from malibu.tui.commands.registry import SlashCommandRegistry

        registry: SlashCommandRegistry = ctx.app.command_registry  # type: ignore[attr-defined]

        if args:
            cmd = registry.get(args[0])
            if cmd is None:
                text = f"[bold red]Unknown command:[/] /{args[0]}"
            else:
                text = (
                    f"[bold]/{cmd.name}[/] - {cmd.description}\n"
                    f"  Usage: {cmd.usage or '/' + cmd.name}"
                )
        else:
            lines = ["[bold]Available commands:[/]"]
            for name, cmd in sorted(registry.all().items()):
                lines.append(f"  [bold]/{name}[/]  {cmd.description}")
            lines.append("\nType /help <command> for detailed usage.")
            text = "\n".join(lines)

        self._post_system(ctx, text)

    @staticmethod
    def _post_system(ctx: CommandContext, text: str) -> None:
        from acp.schema import AgentMessageChunk, TextContentBlock
        from malibu.tui.bridge import SessionUpdateMessage

        update = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text=text),
        )
        ctx.app.post_message(SessionUpdateMessage(ctx.session_id, update))
