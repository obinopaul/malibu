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
    FileChange,
    apply_workspace_edit,
    build_diagnostics,
    find_target_symbol,
    get_retriever_and_wrapper,
    preview_rename_paths,
    relative_path_display,
    resolve_local_edit_paths,
    resolve_mutation_permission,
    resolve_workspace_file,
    workspace_root,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.tools.utils import resolve_file_tool_permission
from vibe.core.types import ToolResultEvent, ToolStreamEvent


class RenameSymbolArgs(BaseModel):
    symbol_name: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    new_name: str = Field(min_length=1)


class RenameSymbolResult(BaseModel):
    summary: str
    applied: bool
    symbol_name: str
    new_name: str
    file_path: str
    changed_files: list[FileChange]
    skipped_files: list[str]
    diagnostics: list[DiagnosticMatch]
    total_changes: int = Field(ge=0)


class RenameSymbolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK


class RenameSymbol(
    BaseTool[RenameSymbolArgs, RenameSymbolResult, RenameSymbolConfig, BaseToolState],
    ToolUIData[RenameSymbolArgs, RenameSymbolResult],
):
    description: ClassVar[str] = (
        "Rename a symbol semantically across the current workspace using LSP rename edits."
    )

    def resolve_permission(self, args: RenameSymbolArgs) -> ToolPermission | None:
        preview_paths = preview_rename_paths(
            symbol_name=args.symbol_name,
            file_path=args.file_path,
            new_name=args.new_name,
        )
        if preview_paths:
            return resolve_mutation_permission(
                preview_paths,
                allowlist=self.config.allowlist,
                denylist=self.config.denylist,
                config_permission=self.config.permission,
            )

        return resolve_file_tool_permission(
            args.file_path,
            allowlist=self.config.allowlist,
            denylist=self.config.denylist,
            config_permission=self.config.permission,
        )

    @classmethod
    def format_call_display(cls, args: RenameSymbolArgs) -> ToolCallDisplay:
        return ToolCallDisplay(
            summary=f"Renaming {args.symbol_name} to {args.new_name}"
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, RenameSymbolResult):
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
        return "Renaming symbol"

    @final
    async def run(
        self, args: RenameSymbolArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | RenameSymbolResult, None]:
        root = workspace_root(ctx)
        file_path = resolve_workspace_file(args.file_path, workspace_root=root)
        retriever, wrapper = get_retriever_and_wrapper(file_path, workspace_root=root)
        target_symbol = find_target_symbol(
            retriever, symbol_name=args.symbol_name, file_path=file_path
        )
        if target_symbol is None:
            yield RenameSymbolResult(
                summary=(
                    f"No symbol named '{args.symbol_name}' was found in "
                    f"{relative_path_display(file_path, workspace_root=root)}"
                ),
                applied=False,
                symbol_name=args.symbol_name,
                new_name=args.new_name,
                file_path=str(file_path),
                changed_files=[],
                skipped_files=[],
                diagnostics=[],
                total_changes=0,
            )
            return

        workspace_edit = retriever.rename_symbol_by_name(
            args.symbol_name,
            str(file_path),
            args.new_name,
        )
        local_paths, skipped_preview = resolve_local_edit_paths(
            workspace_edit,
            workspace_root=root,
        )
        if not workspace_edit or not local_paths:
            skipped_files = skipped_preview or []
            yield RenameSymbolResult(
                summary=(
                    f"No workspace-local rename edits were produced for "
                    f"'{args.symbol_name}'"
                ),
                applied=False,
                symbol_name=args.symbol_name,
                new_name=args.new_name,
                file_path=str(file_path),
                changed_files=[],
                skipped_files=skipped_files,
                diagnostics=[],
                total_changes=0,
            )
            return

        changed_files, skipped_files, total_changes = apply_workspace_edit(
            workspace_edit,
            workspace_root=root,
            position_encoding=str(wrapper.get_position_encoding(file_path)),
        )
        diagnostics = build_diagnostics(
            wrapper, [Path(change.file_path) for change in changed_files]
        )
        skipped_files = [*skipped_preview, *skipped_files]
        yield RenameSymbolResult(
            summary=(
                f"Renamed '{args.symbol_name}' to '{args.new_name}' in "
                f"{len(changed_files)} file(s)"
            ),
            applied=bool(changed_files),
            symbol_name=args.symbol_name,
            new_name=args.new_name,
            file_path=str(file_path),
            changed_files=changed_files,
            skipped_files=sorted(dict.fromkeys(skipped_files)),
            diagnostics=diagnostics,
            total_changes=total_changes,
        )
