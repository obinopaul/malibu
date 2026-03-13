"""Built-in /plan command — invokes the planner subagent.

The planner analyses a task, reads the codebase for context, and produces
a structured step-by-step plan using write_todos.
"""

from __future__ import annotations

from textual.widgets import Static

from malibu.tui.commands.base import BaseCommand, CommandContext


class PlanCommand(BaseCommand):
    name = "plan"
    description = "Invoke the planner agent to create a task plan."
    usage = "/plan <task description>"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        message_list = ctx.app.query_one("MessageList")

        if not args:
            await message_list.add_message(  # type: ignore[attr-type]
                Static(
                    "[yellow]Usage:[/] /plan <task description>\n"
                    "[dim]Example: /plan refactor the auth module to use OAuth2[/]",
                    classes="system-message",
                )
            )
            return

        task = " ".join(args)
        await message_list.add_message(  # type: ignore[attr-type]
            Static(
                f"[cyan]Planning:[/] {task}\n[dim]Invoking planner subagent...[/]",
                classes="system-message",
            )
        )

        try:
            result = await ctx.conn.ext_method(
                "plan",
                {
                    "session_id": ctx.session_id,
                    "task": task,
                },
            )
            plan_output = result.get("plan", "No plan generated.")
            todos = result.get("todos", [])

            if todos:
                todo_lines = "\n".join(
                    f"  [{t.get('status', 'pending')}] {t.get('content', '')}"
                    for t in todos
                )
                await message_list.add_message(  # type: ignore[attr-type]
                    Static(
                        f"[green]Plan created:[/]\n{todo_lines}",
                        classes="system-message",
                    )
                )
            else:
                await message_list.add_message(  # type: ignore[attr-type]
                    Static(
                        f"[green]Plan analysis:[/]\n{plan_output}",
                        classes="system-message",
                    )
                )
        except Exception as exc:
            await message_list.add_message(  # type: ignore[attr-type]
                Static(
                    f"[red]Planning failed:[/] {exc}",
                    classes="system-message",
                )
            )
