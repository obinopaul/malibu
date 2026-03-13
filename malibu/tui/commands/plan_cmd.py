"""Built-in /plan command."""

from __future__ import annotations

from malibu.tui.commands.base import BaseCommand, CommandContext


class PlanCommand(BaseCommand):
    name = "plan"
    description = "Invoke the planner agent to create a task plan."
    usage = "/plan <task description>"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        if not args:
            self._post_system(
                ctx,
                "[yellow]Usage:[/] /plan <task description>\n"
                "[dim]Example:[/] /plan refactor the auth module to use OAuth2",
            )
            return

        task = " ".join(args)
        self._post_system(ctx, f"[dim]Planning:[/] {task}\n[dim]Invoking planner subagent...[/]")

        try:
            result = await ctx.conn.ext_method(
                "plan",
                {
                    "session_id": ctx.session_id,
                    "task": task,
                },
            )
        except Exception as exc:
            self._post_system(ctx, f"[red]Planning failed:[/] {exc}")
            return

        plan_output = str(result.get("plan", "No plan generated."))
        todos = result.get("todos", [])
        if todos:
            todo_lines = "\n".join(
                f"  [{todo.get('status', 'pending')}] {todo.get('content', '')}"
                for todo in todos
            )
            self._post_system(ctx, f"[green]Plan created:[/]\n{todo_lines}")
            return
        self._post_system(ctx, f"[green]Plan analysis:[/]\n{plan_output}")

    @staticmethod
    def _post_system(ctx: CommandContext, text: str) -> None:
        from acp.schema import AgentMessageChunk, TextContentBlock
        from malibu.tui.bridge import SessionUpdateMessage

        update = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text=text),
        )
        ctx.app.post_message(SessionUpdateMessage(ctx.session_id, update))
