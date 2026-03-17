from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import ClassVar, final

from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolPermission,
)
from vibe.core.tools.builtins._lsp_symbol_tool_utils import (
    DiagnosticMatch,
    ReplaceOperationResult,
    SymbolMatch,
    build_diagnostics,
    build_symbol_match,
    find_target_symbol,
    get_retriever_and_wrapper,
    relative_path_display,
    replace_symbol_body_in_file,
    resolve_workspace_file,
    workspace_root,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.tools.utils import resolve_file_tool_permission
from vibe.core.types import ToolResultEvent, ToolStreamEvent


class ReplaceSymbolBodyArgs(BaseModel):
    symbol_name: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    new_body: str = Field(min_length=1)
    preserve_signature: bool = True


class ReplaceSymbolBodyResult(BaseModel):
    summary: str
    applied: bool
    symbol_name: str
    file_path: str
    preserve_signature: bool
    target_symbol: SymbolMatch | None = None
    replacement: ReplaceOperationResult | None = None
    diagnostics: list[DiagnosticMatch]


class ReplaceSymbolBodyConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK


class ReplaceSymbolBody(
    BaseTool[
        ReplaceSymbolBodyArgs,
        ReplaceSymbolBodyResult,
        ReplaceSymbolBodyConfig,
        BaseToolState,
    ],
    ToolUIData[ReplaceSymbolBodyArgs, ReplaceSymbolBodyResult],
):
    description: ClassVar[str] = (
        "Replace the body of a Python or brace-delimited language symbol while preserving its signature when requested."
    )

    def resolve_permission(
        self, args: ReplaceSymbolBodyArgs
    ) -> ToolPermission | None:
        return resolve_file_tool_permission(
            args.file_path,
            allowlist=self.config.allowlist,
            denylist=self.config.denylist,
            config_permission=self.config.permission,
        )

    @classmethod
    def format_call_display(cls, args: ReplaceSymbolBodyArgs) -> ToolCallDisplay:
        return ToolCallDisplay(
            summary=f"Replacing body of {args.symbol_name}",
            content=args.new_body,
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ReplaceSymbolBodyResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )
        warnings = [diag.message for diag in event.result.diagnostics[:3]]
        return ToolResultDisplay(
            success=event.result.applied,
            message=event.result.summary,
            warnings=warnings,
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Replacing symbol body"

    @final
    async def run(
        self, args: ReplaceSymbolBodyArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ReplaceSymbolBodyResult, None]:
        root = workspace_root(ctx)
        file_path = resolve_workspace_file(args.file_path, workspace_root=root)
        retriever, wrapper = get_retriever_and_wrapper(file_path, workspace_root=root)
        target_symbol = find_target_symbol(
            retriever, symbol_name=args.symbol_name, file_path=file_path
        )
        if target_symbol is None:
            yield ReplaceSymbolBodyResult(
                summary=(
                    f"No symbol named '{args.symbol_name}' was found in "
                    f"{relative_path_display(file_path, workspace_root=root)}"
                ),
                applied=False,
                symbol_name=args.symbol_name,
                file_path=str(file_path),
                preserve_signature=args.preserve_signature,
                diagnostics=[],
            )
            return

        replacement = replace_symbol_body_in_file(
            file_path=file_path,
            symbol=target_symbol,
            new_body=args.new_body,
            preserve_signature=args.preserve_signature,
            position_encoding=str(wrapper.get_position_encoding(file_path)),
        )
        diagnostics = build_diagnostics(wrapper, [Path(replacement.file_path)])
        yield ReplaceSymbolBodyResult(
            summary=(
                f"Replaced the body of '{args.symbol_name}' in "
                f"{relative_path_display(file_path, workspace_root=root)}"
            ),
            applied=True,
            symbol_name=args.symbol_name,
            file_path=str(file_path),
            preserve_signature=args.preserve_signature,
            target_symbol=build_symbol_match(target_symbol, include_preview=False),
            replacement=replacement,
            diagnostics=diagnostics,
        )
