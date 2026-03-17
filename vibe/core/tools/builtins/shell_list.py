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
from vibe.core.tools.builtins._shell_sessions import get_shell_manager
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolResultEvent, ToolStreamEvent


class ShellListSession(BaseModel):
    session_name: str
    shell: str
    cwd: str
    state: str


class ShellListArgs(BaseModel):
    include_idle: bool = Field(
        default=True, description="Reserved for future filtering compatibility."
    )


class ShellListResult(BaseModel):
    sessions: list[ShellListSession]


class ShellListConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class ShellList(
    BaseTool[ShellListArgs, ShellListResult, ShellListConfig, BaseToolState],
    ToolUIData[ShellListArgs, ShellListResult],
):
    description: ClassVar[str] = "List active persistent shell sessions."

    async def run(
        self, args: ShellListArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ShellListResult, None]:
        sessions = [
            ShellListSession(
                session_name=session.session_name,
                shell=session.shell,
                cwd=session.cwd,
                state=session.state.value,
            )
            for session in get_shell_manager().list_sessions()
        ]
        yield ShellListResult(sessions=sessions)

    @classmethod
    def format_call_display(cls, args: ShellListArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary="Listing shell sessions")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ShellListResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )
        return ToolResultDisplay(
            success=True, message=f"{len(event.result.sessions)} shell session(s)"
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Listing shell sessions"
