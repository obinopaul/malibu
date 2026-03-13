"""Built-in /skills command — list and manage available skills.

Skills are directory-based packages with SKILL.md files that provide
specialized knowledge and workflows to the agent.
"""

from __future__ import annotations

from textual.widgets import Static

from malibu.tui.commands.base import BaseCommand, CommandContext


class SkillsCommand(BaseCommand):
    name = "skills"
    description = "List available skills or get info about a specific skill."
    usage = "/skills [name]"

    async def execute(self, ctx: CommandContext, args: list[str]) -> None:
        message_list = ctx.app.query_one("MessageList")

        try:
            result = await ctx.conn.ext_method(
                "skills",
                {
                    "session_id": ctx.session_id,
                    "action": "info" if args else "list",
                    "skill_name": args[0] if args else None,
                },
            )

            if args:
                # Info about a specific skill
                skill = result.get("skill")
                if skill:
                    instructions = skill.get("instructions", "")
                    preview = instructions[:500] + "..." if len(instructions) > 500 else instructions
                    await message_list.add_message(  # type: ignore[attr-type]
                        Static(
                            f"[bold cyan]{skill['name']}[/]\n"
                            f"[dim]Source:[/] {skill.get('source', 'unknown')}\n"
                            f"[dim]Description:[/] {skill.get('description', 'N/A')}\n\n"
                            f"[dim]Instructions preview:[/]\n{preview}",
                            classes="system-message",
                        )
                    )
                else:
                    await message_list.add_message(  # type: ignore[attr-type]
                        Static(
                            f"[yellow]Skill not found:[/] {args[0]}",
                            classes="system-message",
                        )
                    )
            else:
                # List all skills
                skills = result.get("skills", [])
                if skills:
                    lines = ["[bold]Available Skills:[/]\n"]
                    for s in skills:
                        status = "[green]✓[/]" if s.get("enabled", True) else "[red]✗[/]"
                        source = f"[dim]({s.get('source', 'unknown')})[/]"
                        lines.append(f"  {status} [cyan]{s['name']}[/] {source}")
                        lines.append(f"      [dim]{s.get('description', '')[:60]}...[/]" if len(s.get('description', '')) > 60 else f"      [dim]{s.get('description', '')}[/]")
                    await message_list.add_message(  # type: ignore[attr-type]
                        Static("\n".join(lines), classes="system-message")
                    )
                else:
                    await message_list.add_message(  # type: ignore[attr-type]
                        Static(
                            "[dim]No skills found.[/]\n"
                            "[dim]Skills are loaded from:[/]\n"
                            "  • malibu/skills/builtin/ (built-in)\n"
                            "  • ~/.malibu/skills/ (user)\n"
                            "  • ~/.agents/skills/ (user, shared)\n"
                            "  • .malibu/skills/ (project)\n"
                            "  • .agents/skills/ (project, shared)",
                            classes="system-message",
                        )
                    )
        except Exception as exc:
            await message_list.add_message(  # type: ignore[attr-type]
                Static(
                    f"[red]Error listing skills:[/] {exc}",
                    classes="system-message",
                )
            )
