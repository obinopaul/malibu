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
    ReferenceMatch,
    build_reference_matches,
    find_target_symbol,
    get_retriever_and_wrapper,
    relative_path_display,
    resolve_workspace_file,
    workspace_root,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.tools.utils import resolve_file_tool_permission
from vibe.core.types import ToolResultEvent, ToolStreamEvent


class FindReferencingSymbolsArgs(BaseModel):
    symbol_name: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    include_declaration: bool = True


class FindReferencingSymbolsResult(BaseModel):
    summary: str
    symbol_name: str
    file_path: str
    include_declaration: bool
    references: list[ReferenceMatch]
    file_count: int


class FindReferencingSymbolsConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class FindReferencingSymbols(
    BaseTool[
        FindReferencingSymbolsArgs,
        FindReferencingSymbolsResult,
        FindReferencingSymbolsConfig,
        BaseToolState,
    ],
    ToolUIData[FindReferencingSymbolsArgs, FindReferencingSymbolsResult],
):
    description: ClassVar[str] = (
        "Find semantic references to a symbol using the native LSP backend."
    )

    def resolve_permission(
        self, args: FindReferencingSymbolsArgs
    ) -> ToolPermission | None:
        return resolve_file_tool_permission(
            args.file_path,
            allowlist=self.config.allowlist,
            denylist=self.config.denylist,
            config_permission=self.config.permission,
        )

    @classmethod
    def format_call_display(
        cls, args: FindReferencingSymbolsArgs
    ) -> ToolCallDisplay:
        return ToolCallDisplay(
            summary=f"Finding references to {args.symbol_name} in {Path(args.file_path).name}"
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, FindReferencingSymbolsResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )
        return ToolResultDisplay(success=True, message=event.result.summary)

    @classmethod
    def get_status_text(cls) -> str:
        return "Finding references"

    @final
    async def run(
        self, args: FindReferencingSymbolsArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | FindReferencingSymbolsResult, None]:
        root = workspace_root(ctx)
        file_path = resolve_workspace_file(args.file_path, workspace_root=root)
        retriever, _ = get_retriever_and_wrapper(file_path, workspace_root=root)
        target_symbol = find_target_symbol(
            retriever, symbol_name=args.symbol_name, file_path=file_path
        )
        if target_symbol is None:
            yield FindReferencingSymbolsResult(
                summary=(
                    f"No symbol named '{args.symbol_name}' was found in "
                    f"{relative_path_display(file_path, workspace_root=root)}"
                ),
                symbol_name=args.symbol_name,
                file_path=str(file_path),
                include_declaration=args.include_declaration,
                references=[],
                file_count=0,
            )
            return

        references = retriever.find_references(
            str(file_path),
            target_symbol.start_line,
            target_symbol.start_character,
            args.include_declaration,
        )
        matches = build_reference_matches(
            references,
            include_declaration=args.include_declaration,
            declaration_symbol=target_symbol,
            workspace_root=root,
        )
        file_count = len({match.file_path for match in matches})
        yield FindReferencingSymbolsResult(
            summary=(
                f"Found {len(matches)} reference(s) to '{args.symbol_name}' across "
                f"{file_count} file(s)"
            ),
            symbol_name=args.symbol_name,
            file_path=str(file_path),
            include_declaration=args.include_declaration,
            references=matches,
            file_count=file_count,
        )
