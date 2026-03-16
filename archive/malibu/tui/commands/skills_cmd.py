"""Built-in /skills command."""

from __future__ import annotations

from malibu.tui.commands.base import BaseCommand, CommandContext


class SkillsCommand(BaseCommand):
    name = "skills"
    description = "List available skills or inspect one skill."
    usage = "/skills [name]"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        try:
            result = await ctx.conn.ext_method(
                "skills",
                {
                    "session_id": ctx.session_id,
                    "action": "info" if args else "list",
                    "skill_name": args[0] if args else None,
                },
            )
        except Exception as exc:
            self._post_system(ctx, f"[red]Error listing skills:[/] {exc}")
            return

        if args:
            skill = result.get("skill")
            if not skill:
                self._post_system(ctx, f"[yellow]Skill not found:[/] {args[0]}")
                return
            instructions = str(skill.get("instructions", ""))
            preview = instructions[:500] + "..." if len(instructions) > 500 else instructions
            self._post_system(
                ctx,
                f"[bold cyan]{skill['name']}[/]\n"
                f"[dim]Source:[/] {skill.get('source', 'unknown')}\n"
                f"[dim]Description:[/] {skill.get('description', 'N/A')}\n\n"
                f"[dim]Instructions preview:[/]\n{preview}",
            )
            return

        skills = result.get("skills", [])
        if not skills:
            self._post_system(
                ctx,
                "[dim]No skills found.[/]\n"
                "[dim]Skills are loaded from:[/]\n"
                "  • malibu/skills/builtin/\n"
                "  • ~/.malibu/skills/\n"
                "  • ~/.agents/skills/\n"
                "  • .malibu/skills/\n"
                "  • .agents/skills/",
            )
            return

        lines = ["[bold]Available Skills:[/]\n"]
        for skill in skills:
            status = "[green]✓[/]" if skill.get("enabled", True) else "[red]✗[/]"
            source = f"[dim]({skill.get('source', 'unknown')})[/]"
            description = str(skill.get("description", ""))
            short_description = description[:60] + "..." if len(description) > 60 else description
            lines.append(f"  {status} [cyan]{skill['name']}[/] {source}")
            lines.append(f"      [dim]{short_description}[/]")
        self._post_system(ctx, "\n".join(lines))

    @staticmethod
    def _post_system(ctx: CommandContext, text: str) -> None:
        from acp.schema import AgentMessageChunk, TextContentBlock
        from malibu.tui.bridge import SessionUpdateMessage

        update = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text=text),
        )
        ctx.app.post_message(SessionUpdateMessage(ctx.session_id, update))
