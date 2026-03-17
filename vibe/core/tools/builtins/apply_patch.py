from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import ClassVar, final

from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.builtins._apply_patch_utils import (
    ActionType,
    DiffError,
    identify_changed_files,
    process_patch,
)
from vibe.core.tools.builtins._file_tool_utils import (
    ensure_existing_file,
    ensure_parent_directory,
    resolve_tool_path,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.tools.utils import resolve_file_tool_permission
from vibe.core.types import ToolResultEvent, ToolStreamEvent


class ApplyPatchArgs(BaseModel):
    input: str = Field(description="Patch payload in the Malibu apply_patch format.")


class ApplyPatchMove(BaseModel):
    from_path: str
    to_path: str


class ApplyPatchResult(BaseModel):
    applied: bool
    fuzz: int
    changed_paths: list[str]
    created_paths: list[str] = Field(default_factory=list)
    modified_paths: list[str] = Field(default_factory=list)
    deleted_paths: list[str] = Field(default_factory=list)
    moves: list[ApplyPatchMove] = Field(default_factory=list)
    patch: str


class ApplyPatchConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK


class ApplyPatch(
    BaseTool[ApplyPatchArgs, ApplyPatchResult, ApplyPatchConfig, BaseToolState],
    ToolUIData[ApplyPatchArgs, ApplyPatchResult],
):
    description: ClassVar[str] = (
        "Apply structured multi-file patches with add, update, move, and delete operations."
    )

    def resolve_permission(self, args: ApplyPatchArgs) -> ToolPermission | None:
        changed_files = identify_changed_files(args.input)
        if not changed_files:
            return self.config.permission

        saw_always = False
        saw_ask = False
        saw_default = False
        for path_str in changed_files:
            permission = resolve_file_tool_permission(
                path_str,
                allowlist=self.config.allowlist,
                denylist=self.config.denylist,
                config_permission=self.config.permission,
            )
            if permission is ToolPermission.NEVER:
                return ToolPermission.NEVER
            if permission is ToolPermission.ALWAYS:
                saw_always = True
                continue
            if permission is ToolPermission.ASK:
                saw_ask = True
                continue
            saw_default = True

        if saw_ask:
            return ToolPermission.ASK
        if saw_always and not saw_default:
            return ToolPermission.ALWAYS
        return None

    @final
    async def run(
        self, args: ApplyPatchArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ApplyPatchResult, None]:
        patch_text = args.input.strip()
        if not patch_text:
            raise ToolError("Patch input cannot be empty")

        try:
            commit, fuzz = process_patch(
                patch_text,
                open_fn=self._open_file,
                write_fn=self._write_file,
                remove_fn=self._remove_file,
            )
        except DiffError as exc:
            raise ToolError(str(exc)) from exc

        created_paths: list[str] = []
        modified_paths: list[str] = []
        deleted_paths: list[str] = []
        moves: list[ApplyPatchMove] = []

        for path, change in commit.changes.items():
            resolved_path = str(resolve_tool_path(path))
            match change.type:
                case ActionType.ADD:
                    created_paths.append(resolved_path)
                case ActionType.DELETE:
                    deleted_paths.append(resolved_path)
                case ActionType.UPDATE:
                    modified_paths.append(
                        str(resolve_tool_path(change.move_path or path))
                    )
                    if change.move_path:
                        moves.append(
                            ApplyPatchMove(
                                from_path=resolved_path,
                                to_path=str(resolve_tool_path(change.move_path)),
                            )
                        )

        changed_paths = sorted({
            *created_paths,
            *modified_paths,
            *deleted_paths,
            *(move.from_path for move in moves),
            *(move.to_path for move in moves),
        })

        yield ApplyPatchResult(
            applied=True,
            fuzz=fuzz,
            changed_paths=changed_paths,
            created_paths=sorted(created_paths),
            modified_paths=sorted(modified_paths),
            deleted_paths=sorted(deleted_paths),
            moves=moves,
            patch=patch_text,
        )

    def _open_file(self, path_str: str) -> str:
        path = ensure_existing_file(resolve_tool_path(path_str))
        try:
            return path.read_text("utf-8")
        except UnicodeDecodeError as exc:
            raise DiffError(f"Cannot patch binary file: {path}") from exc
        except OSError as exc:
            raise DiffError(f"Failed to read file {path}: {exc}") from exc

    def _write_file(self, path_str: str, content: str) -> None:
        path = resolve_tool_path(path_str)
        if path.exists() and path.is_dir():
            raise DiffError(f"Cannot write file over directory: {path}")

        ensure_parent_directory(path, create=True)
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise DiffError(f"Failed to write file {path}: {exc}") from exc

    def _remove_file(self, path_str: str) -> None:
        path = ensure_existing_file(resolve_tool_path(path_str))
        try:
            path.unlink()
        except OSError as exc:
            raise DiffError(f"Failed to remove file {path}: {exc}") from exc

    @classmethod
    def format_call_display(cls, args: ApplyPatchArgs) -> ToolCallDisplay:
        changed_files = identify_changed_files(args.input)
        summary = f"Applying patch ({len(changed_files)} file{'' if len(changed_files) == 1 else 's'})"
        return ToolCallDisplay(summary=summary, content=args.input)

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ApplyPatchResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        warnings = []
        if event.result.fuzz:
            warnings.append(f"Patch applied with fuzz={event.result.fuzz}")

        message = (
            f"Patched {len(event.result.changed_paths)} file"
            f"{'' if len(event.result.changed_paths) == 1 else 's'}"
        )
        return ToolResultDisplay(success=True, message=message, warnings=warnings)

    @classmethod
    def get_status_text(cls) -> str:
        return "Applying patch"
