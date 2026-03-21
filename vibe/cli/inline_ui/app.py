# vibe/cli/inline_ui/app.py
"""Main orchestrator for the Rich + prompt_toolkit inline UI."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from rich.console import Console

from vibe import __version__ as CORE_VERSION
from vibe.cli.commands import CommandRegistry
from vibe.cli.inline_ui.approval import prompt_approval
from vibe.cli.inline_ui.banner import print_banner
from vibe.cli.inline_ui.event_handler import InlineEventHandler
from vibe.cli.inline_ui.input_session import InputSession
from vibe.cli.inline_ui.notifications import InlineNotificationAdapter, NotificationContext
from vibe.cli.inline_ui.question import prompt_question
from vibe.cli.inline_ui.renderer import OutputRenderer
from vibe.cli.inline_ui.spinner import WaitingSpinner
from vibe.cli.inline_ui.status import print_status
from vibe.cli.inline_ui.tool_display import ToolDisplay
from vibe.core.agent_loop import AgentLoop
from vibe.core.autocompletion.path_prompt_adapter import render_path_prompt
from vibe.core.logger import logger
from vibe.core.paths import HISTORY_FILE
from vibe.core.tools.base import ToolPermission
from vibe.core.tools.builtins.ask_user_question import (
    AskUserQuestionArgs,
    AskUserQuestionResult,
)
from vibe.core.types import (
    ApprovalResponse,
    AssistantEvent,
    RateLimitError,
)
from vibe.core.utils import (
    CancellationReason,
    get_user_cancellation_message,
)


class InlineApp:
    """Main application class for the inline UI."""

    def __init__(
        self,
        agent_loop: AgentLoop,
        initial_prompt: str | None = None,
        teleport_on_start: bool = False,
    ) -> None:
        self.agent_loop = agent_loop
        self._initial_prompt = initial_prompt
        self._tools_collapsed = True

        self.console = Console(highlight=False)
        self.renderer = OutputRenderer()
        self.tool_display = ToolDisplay()

        self._notifier = InlineNotificationAdapter(
            get_enabled=lambda: self.agent_loop.config.enable_notifications,
        )

        excluded = []
        if not self.agent_loop.config.nuage_enabled:
            excluded.append("teleport")
        self.commands = CommandRegistry(excluded_commands=excluded)

        cmd_list = [
            (f"/{name}", cmd.description)
            for name, cmd in self.commands.commands.items()
        ]

        self.input_session = InputSession(
            history_file=HISTORY_FILE.path,
            commands=cmd_list,
        )

        self.event_handler = InlineEventHandler(
            renderer=self.renderer,
            tool_display=self.tool_display,
            tools_collapsed=self._tools_collapsed,
        )

    async def _approval_callback(
        self, tool: str, args: BaseModel, tool_call_id: str
    ) -> tuple[ApprovalResponse, str | None]:
        if self.agent_loop.config.auto_approve:
            return (ApprovalResponse.YES, None)

        tool_cfg = self.agent_loop.config.tools.get(tool)
        if tool_cfg and tool_cfg.permission == ToolPermission.ALWAYS:
            return (ApprovalResponse.YES, None)

        self._notifier.notify(NotificationContext.ACTION_REQUIRED)
        response, feedback = await prompt_approval(
            tool, args, console=self.console
        )

        if feedback == "__always__":
            self.agent_loop.set_tool_permission(
                tool, ToolPermission.ALWAYS, save_permanently=False
            )
            return (ApprovalResponse.YES, None)

        return (response, feedback)

    async def _user_input_callback(self, args: BaseModel) -> BaseModel:
        self._notifier.notify(NotificationContext.ACTION_REQUIRED)
        from typing import cast
        question_args = cast(AskUserQuestionArgs, args)
        return await prompt_question(question_args, console=self.console)

    async def _handle_agent_turn(self, prompt: str) -> None:
        spinner = WaitingSpinner()
        spinner.start()

        try:
            rendered_prompt = render_path_prompt(prompt, base_dir=Path.cwd())
            first_content = True

            async for event in self.agent_loop.act(rendered_prompt):
                if first_content and isinstance(event, AssistantEvent) and event.content:
                    spinner.stop()
                    first_content = False

                await self.event_handler.handle_event(event)

        except asyncio.CancelledError:
            spinner.stop()
            self.event_handler.finalize()
            raise
        except RateLimitError:
            spinner.stop()
            self.renderer.error(
                "Rate limits exceeded. Please wait a moment."
            )
        except Exception as e:
            spinner.stop()
            self.renderer.error(str(e))
        finally:
            if first_content:
                spinner.stop()
            self.event_handler.finalize()
            self._notifier.notify(NotificationContext.COMPLETE)

    async def _handle_command(self, user_input: str) -> bool:
        command_name, _, command_args = user_input.partition(" ")
        command = self.commands.find_command(command_name)
        if not command:
            return False

        self.renderer.user_message(user_input)

        if command_name == "/help":
            help_text = self.commands.get_help_text()
            self.renderer.command_message(help_text)
        elif command_name == "/clear":
            await self.agent_loop.clear_history()
            self.renderer.command_message("Conversation history cleared!")
        elif command_name == "/status":
            stats = self.agent_loop.stats
            self.renderer.command_message(
                f"Steps: {stats.steps} | "
                f"Tokens: {stats.session_total_llm_tokens:,} | "
                f"Cost: ${stats.session_cost:.4f}"
            )
        elif command_name == "/compact":
            old_tokens = self.agent_loop.stats.context_tokens
            await self.agent_loop.compact()
            new_tokens = self.agent_loop.stats.context_tokens
            saved = old_tokens - new_tokens
            self.renderer.command_message(
                f"Compacted: {old_tokens:,} -> {new_tokens:,} tokens "
                f"(saved {saved:,})"
            )
        elif command_name in ("/config", "/model"):
            self.renderer.warning(
                "Interactive config requires the TUI mode (malibu --tui). "
                "Edit ~/.config/malibu/config.yaml directly."
            )
        else:
            self.renderer.command_message(f"Command `{command_name}` executed.")

        return True

    async def _handle_bash(self, command: str) -> None:
        if not command:
            self.renderer.error("No command provided after '!'")
            return
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=False, timeout=30
            )
            stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
            stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
            output = stdout or stderr or "(no output)"
            self.renderer.bash_output(command, output, result.returncode)
        except subprocess.TimeoutExpired:
            self.renderer.error("Command timed out after 30 seconds")
        except Exception as e:
            self.renderer.error(f"Command failed: {e}")

    async def run(self) -> str | None:
        self.agent_loop.set_approval_callback(self._approval_callback)
        self.agent_loop.set_user_input_callback(self._user_input_callback)

        config = self.agent_loop.config
        active_model = config.get_active_model()
        print_banner(
            model_name=active_model.alias,
            version=CORE_VERSION,
            agent_name=self.agent_loop.agent_profile.display_name.lower(),
        )

        if self._initial_prompt:
            self.renderer.user_message(self._initial_prompt)
            await self._handle_agent_turn(self._initial_prompt)

        while True:
            try:
                user_input = await self.input_session.prompt_async("> ")
            except (EOFError, KeyboardInterrupt):
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.startswith("!"):
                await self._handle_bash(user_input[1:])
                continue

            if user_input.startswith("/"):
                if await self._handle_command(user_input):
                    continue

            self.renderer.user_message(user_input)
            await self._handle_agent_turn(user_input)

        if self.agent_loop.session_logger.enabled:
            return self.agent_loop.session_logger.session_id
        return None


def run_inline_ui(
    agent_loop: AgentLoop,
    initial_prompt: str | None = None,
    teleport_on_start: bool = False,
) -> None:
    """Entry point for the Rich + prompt_toolkit inline UI."""
    app = InlineApp(
        agent_loop=agent_loop,
        initial_prompt=initial_prompt,
        teleport_on_start=teleport_on_start,
    )
    session_id = asyncio.run(app.run())
    if session_id:
        print()
        print("To continue this session, run: malibu --continue")
        print(f"Or: malibu --resume {session_id}")
