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
    InsertOperationResult,
    SymbolMatch,
    build_diagnostics,
    build_symbol_match,
    find_target_symbol,
    get_retriever_and_wrapper,
    insert_relative_to_symbol,
    relative_path_display,
    resolve_workspace_file,
    workspace_root,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.tools.utils import resolve_file_tool_permission
from vibe.core.types import ToolResultEvent, ToolStreamEvent


class InsertAfterSymbolArgs(BaseModel):
    symbol_name: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    content: str = Field(min_length=1)


class InsertAfterSymbolResult(BaseModel):
    summary: str
    applied: bool
    symbol_name: str
    file_path: str
    target_symbol: SymbolMatch | None = None
    insertion: InsertOperationResult | None = None
    diagnostics: list[DiagnosticMatch]


class InsertAfterSymbolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK


class InsertAfterSymbol(
    BaseTool[
        InsertAfterSymbolArgs,
        InsertAfterSymbolResult,
        InsertAfterSymbolConfig,
        BaseToolState,
    ],
    ToolUIData[InsertAfterSymbolArgs, InsertAfterSymbolResult],
):
    description: ClassVar[str] = (
        "Insert content immediately after a symbol using LSP symbol ranges and workspace-local edits."
    )

    def resolve_permission(
        self, args: InsertAfterSymbolArgs
    ) -> ToolPermission | None:
        return resolve_file_tool_permission(
            args.file_path,
            allowlist=self.config.allowlist,
            denylist=self.config.denylist,
            config_permission=self.config.permission,
        )

    @classmethod
    def format_call_display(cls, args: InsertAfterSymbolArgs) -> ToolCallDisplay:
        return ToolCallDisplay(
            summary=f"Inserting after {args.symbol_name}",
            content=args.content,
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, InsertAfterSymbolResult):
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
        return "Inserting after symbol"

    @final
    async def run(
        self, args: InsertAfterSymbolArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | InsertAfterSymbolResult, None]:
        root = workspace_root(ctx)
        file_path = resolve_workspace_file(args.file_path, workspace_root=root)
        retriever, wrapper = get_retriever_and_wrapper(file_path, workspace_root=root)
        target_symbol = find_target_symbol(
            retriever, symbol_name=args.symbol_name, file_path=file_path
        )
        if target_symbol is None:
            yield InsertAfterSymbolResult(
                summary=(
                    f"No symbol named '{args.symbol_name}' was found in "
                    f"{relative_path_display(file_path, workspace_root=root)}"
                ),
                applied=False,
                symbol_name=args.symbol_name,
                file_path=str(file_path),
                diagnostics=[],
            )
            return

        insertion = insert_relative_to_symbol(
            file_path=file_path,
            symbol=target_symbol,
            content=args.content,
            position="after",
            position_encoding=str(wrapper.get_position_encoding(file_path)),
        )
        diagnostics = build_diagnostics(wrapper, [Path(insertion.file_path)])
        yield InsertAfterSymbolResult(
            summary=(
                f"Inserted content after '{args.symbol_name}' in "
                f"{relative_path_display(file_path, workspace_root=root)}"
            ),
            applied=True,
            symbol_name=args.symbol_name,
            file_path=str(file_path),
            target_symbol=build_symbol_match(target_symbol, include_preview=False),
            insertion=insertion,
            diagnostics=diagnostics,
        )
