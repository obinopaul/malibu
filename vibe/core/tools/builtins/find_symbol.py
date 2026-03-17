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
    SymbolMatch,
    build_symbol_match,
    get_retriever_and_wrapper,
    relative_path_display,
    resolve_workspace_file,
    workspace_root,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.tools.utils import resolve_file_tool_permission
from vibe.core.types import ToolResultEvent, ToolStreamEvent


class FindSymbolArgs(BaseModel):
    symbol_name: str = Field(min_length=1)
    file_path: str | None = None


class FindSymbolResult(BaseModel):
    summary: str
    symbol_name: str
    file_path: str | None = None
    symbols: list[SymbolMatch]


class FindSymbolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class FindSymbol(
    BaseTool[FindSymbolArgs, FindSymbolResult, FindSymbolConfig, BaseToolState],
    ToolUIData[FindSymbolArgs, FindSymbolResult],
):
    description: ClassVar[str] = (
        "Find workspace symbols semantically using the native LSP backend. "
        "Optionally restrict the search to one file."
    )

    def resolve_permission(self, args: FindSymbolArgs) -> ToolPermission | None:
        if args.file_path is None:
            return None
        return resolve_file_tool_permission(
            args.file_path,
            allowlist=self.config.allowlist,
            denylist=self.config.denylist,
            config_permission=self.config.permission,
        )

    @classmethod
    def format_call_display(cls, args: FindSymbolArgs) -> ToolCallDisplay:
        summary = f"Finding symbol {args.symbol_name}"
        if args.file_path:
            summary = f"{summary} in {Path(args.file_path).name}"
        return ToolCallDisplay(summary=summary)

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, FindSymbolResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )
        return ToolResultDisplay(success=True, message=event.result.summary)

    @classmethod
    def get_status_text(cls) -> str:
        return "Finding symbol"

    @final
    async def run(
        self, args: FindSymbolArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | FindSymbolResult, None]:
        root = workspace_root(ctx)
        file_path = (
            resolve_workspace_file(args.file_path, workspace_root=root)
            if args.file_path
            else None
        )
        retriever, _ = get_retriever_and_wrapper(file_path, workspace_root=root)
        symbols = retriever.find_symbol(
            args.symbol_name,
            str(file_path) if file_path else None,
        )
        matches = [build_symbol_match(symbol) for symbol in symbols]

        search_scope = (
            relative_path_display(file_path, workspace_root=root)
            if file_path
            else "the workspace"
        )
        summary = (
            f"Found {len(matches)} symbol(s) matching '{args.symbol_name}' in {search_scope}"
        )
        yield FindSymbolResult(
            summary=summary,
            symbol_name=args.symbol_name,
            file_path=str(file_path) if file_path else None,
            symbols=matches,
        )
