from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import ClassVar

from pydantic import BaseModel

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


class ShellViewArgs(BaseModel):
    session_name: str


class ShellViewConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class ShellView(
    BaseTool[ShellViewArgs, ShellCommandSnapshot, ShellViewConfig, BaseToolState],
    ToolUIData[ShellViewArgs, ShellCommandSnapshot],
):
    description: ClassVar[str] = "View the current buffered output of a shell session."

    async def run(
        self, args: ShellViewArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ShellCommandSnapshot, None]:
        yield get_shell_manager().get_session_output(args.session_name)

    @classmethod
    def format_call_display(cls, args: ShellViewArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary=f"Viewing shell session {args.session_name}")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ShellCommandSnapshot):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )
        return ToolResultDisplay(
            success=True,
            message=f"{event.result.session_name}: {'running' if event.result.running else 'idle'}",
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Viewing shell session"
