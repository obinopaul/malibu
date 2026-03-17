from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import ClassVar

from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.builtins._shell_sessions import (
    ShellBusyError,
    ShellCommandSnapshot,
    ShellCommandTimeoutError,
    get_shell_manager,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolResultEvent, ToolStreamEvent


class ShellRunArgs(BaseModel):
    session_name: str
    command: str
    run_directory: str | None = Field(
        default=None,
        description="Optional working directory override for this command.",
    )
    timeout: int | None = Field(
        default=None, description="Override the default timeout for the command."
    )
    wait_for_output: bool = Field(
        default=True,
        description="Wait for command completion. Set false for long-running tasks.",
    )


class ShellRunConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    default_timeout: int = Field(default=300, description="Default timeout in seconds.")
    max_timeout: int = Field(default=1800, description="Maximum timeout in seconds.")


class ShellRun(
    BaseTool[ShellRunArgs, ShellCommandSnapshot, ShellRunConfig, BaseToolState],
    ToolUIData[ShellRunArgs, ShellCommandSnapshot],
):
    description: ClassVar[str] = (
        "Run a command inside a persistent shell session, optionally in the background."
    )

    async def run(
        self, args: ShellRunArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ShellCommandSnapshot, None]:
        timeout = self._resolve_timeout(args.timeout)
        try:
            yield get_shell_manager().run_command(
                session_name=args.session_name,
                command=args.command,
                run_directory=args.run_directory,
                timeout=timeout,
                wait_for_output=args.wait_for_output,
            )
        except ShellCommandTimeoutError as exc:
            raise ToolError(str(exc)) from exc
        except ShellBusyError as exc:
            raise ToolError(str(exc)) from exc

    def _resolve_timeout(self, timeout: int | None) -> int:
        if timeout is None:
            return self.config.default_timeout
        if timeout <= 0:
            raise ToolError("Timeout must be a positive number")
        if timeout > self.config.max_timeout:
            raise ToolError(f"Timeout cannot exceed {self.config.max_timeout} seconds")
        return timeout

    @classmethod
    def format_call_display(cls, args: ShellRunArgs) -> ToolCallDisplay:
        mode = "background" if not args.wait_for_output else "wait"
        return ToolCallDisplay(
            summary=f"shell[{args.session_name}] ({mode})", content=args.command
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ShellCommandSnapshot):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )
        state = "running" if event.result.running else "completed"
        return ToolResultDisplay(
            success=True, message=f"{event.result.session_name}: {state}"
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Running shell command"
