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
from vibe.core.tools.builtins._shell_sessions import ShellSessionInfo, get_shell_manager
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolResultEvent, ToolStreamEvent


class ShellInitArgs(BaseModel):
    session_name: str
    start_directory: str | None = Field(
        default=None, description="Optional directory to start the shell session in."
    )


class ShellInitResult(BaseModel):
    session_name: str
    shell: str
    cwd: str
    state: str


class ShellInitConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK


class ShellInit(
    BaseTool[ShellInitArgs, ShellInitResult, ShellInitConfig, BaseToolState],
    ToolUIData[ShellInitArgs, ShellInitResult],
):
    description: ClassVar[str] = "Start a persistent interactive shell session."

    async def run(
        self, args: ShellInitArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ShellInitResult, None]:
        session = get_shell_manager().create_session(
            args.session_name, args.start_directory
        )
        yield self._build_result(session)

    def _build_result(self, session: ShellSessionInfo) -> ShellInitResult:
        return ShellInitResult(
            session_name=session.session_name,
            shell=session.shell,
            cwd=session.cwd,
            state=session.state.value,
        )

    @classmethod
    def format_call_display(cls, args: ShellInitArgs) -> ToolCallDisplay:
        return ToolCallDisplay(
            summary=f"Starting shell session {args.session_name}",
            content=args.start_directory,
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ShellInitResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )
        return ToolResultDisplay(
            success=True,
            message=f"Started {event.result.session_name} in {event.result.cwd}",
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Starting shell session"
