from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import ClassVar

from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolPermission,
)
from vibe.core.tools.builtins._shell_sessions import (
    ShellCommandSnapshot,
    get_shell_manager,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolResultEvent, ToolStreamEvent


class ShellStopArgs(BaseModel):
    session_name: str
    kill_session: bool = Field(
        default=False,
        description="Kill the session entirely instead of interrupting the current command.",
    )


class ShellStopResult(ShellCommandSnapshot):
    session_terminated: bool = False


class ShellStopConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK


class ShellStop(
    BaseTool[ShellStopArgs, ShellStopResult, ShellStopConfig, BaseToolState],
    ToolUIData[ShellStopArgs, ShellStopResult],
):
    description: ClassVar[str] = (
        "Interrupt the current shell command or terminate the whole shell session."
    )

    async def run(
        self, args: ShellStopArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ShellStopResult, None]:
        manager = get_shell_manager()
        snapshot = manager.stop_current_command(
            args.session_name, kill_session=args.kill_session
        )
        session_terminated = args.kill_session or not any(
            session.session_name == args.session_name for session in manager.list_sessions()
        )
        yield ShellStopResult(
            **snapshot.model_dump(),
            session_terminated=session_terminated,
        )

    @classmethod
    def format_call_display(cls, args: ShellStopArgs) -> ToolCallDisplay:
        action = "Killing" if args.kill_session else "Stopping"
        return ToolCallDisplay(summary=f"{action} shell session {args.session_name}")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ShellStopResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )
        action = "Killed" if event.result.session_terminated else "Stopped"
        return ToolResultDisplay(
            success=True, message=f"{action} {event.result.session_name}"
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Stopping shell session"
