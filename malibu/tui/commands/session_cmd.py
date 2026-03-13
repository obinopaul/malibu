"""Built-in /session command."""

from __future__ import annotations

from malibu.tui.commands.base import BaseCommand, CommandContext


class SessionCommand(BaseCommand):
    name = "session"
    description = "Manage sessions: list, new, resume, or fork."
    usage = "/session [list|new|resume <id>|fork]"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        if not args:
            self._post_system(
                ctx,
                "[bold]Session subcommands:[/]\n"
                "  list           - Browse existing sessions\n"
                "  new            - Start a fresh session\n"
                "  resume <id>    - Resume a previous session\n"
                "  fork           - Fork the current session",
            )
            return

        subcommand = args[0].lower()

        if subcommand == "list":
            sessions = await ctx.conn.list_sessions()
            from malibu.tui.screens import SessionBrowserScreen

            ctx.app.push_screen(SessionBrowserScreen(sessions))

        elif subcommand == "new":
            result = await ctx.conn.new_session()
            ctx.app.session_id = result.session_id  # type: ignore[attr-defined]
            self._post_system(
                ctx, f"[dim]New session started: {result.session_id}[/]"
            )

        elif subcommand == "resume":
            if len(args) < 2:
                self._post_system(
                    ctx,
                    "[bold red]Usage:[/] /session resume <session_id>",
                )
                return
            session_id = args[1]
            await ctx.conn.resume_session(session_id=session_id)
            ctx.app.session_id = session_id  # type: ignore[attr-defined]
            self._post_system(ctx, f"[dim]Resumed session {session_id}[/]")

        elif subcommand == "fork":
            result = await ctx.conn.fork_session(session_id=ctx.session_id)
            ctx.app.session_id = result.session_id  # type: ignore[attr-defined]
            self._post_system(
                ctx, f"[dim]Forked to new session {result.session_id}[/]"
            )

        else:
            self._post_system(
                ctx, f"[bold red]Unknown subcommand:[/] {subcommand}"
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
