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


class ShellWriteArgs(BaseModel):
    session_name: str
    input: str
    press_enter: bool = Field(
        default=True, description="Press Enter after sending the input."
    )


class ShellWriteConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK


class ShellWrite(
    BaseTool[ShellWriteArgs, ShellCommandSnapshot, ShellWriteConfig, BaseToolState],
    ToolUIData[ShellWriteArgs, ShellCommandSnapshot],
):
    description: ClassVar[str] = "Write input into an existing shell session."

    async def run(
        self, args: ShellWriteArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ShellCommandSnapshot, None]:
        yield get_shell_manager().write_to_process(
            args.session_name, args.input, press_enter=args.press_enter
        )

    @classmethod
    def format_call_display(cls, args: ShellWriteArgs) -> ToolCallDisplay:
        return ToolCallDisplay(
            summary=f"Writing to shell session {args.session_name}", content=args.input
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ShellCommandSnapshot):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )
        return ToolResultDisplay(
            success=True, message=f"Wrote input to {event.result.session_name}"
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Writing to shell session"
