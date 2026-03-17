from __future__ import annotations

from collections.abc import AsyncGenerator
from enum import StrEnum, auto
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field, model_validator

from vibe.core.git import GitOperations
from vibe.core.snapshot import SnapshotManager
from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolPermission,
)
from vibe.core.tools.builtins._git_support import (
    resolve_directory,
    snapshot_project_root,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolStreamEvent


class SnapshotAction(StrEnum):
    TAKE = auto()
    LIST = auto()
    DIFF = auto()
    REVERT = auto()
    CLEANUP = auto()


class SnapshotArgs(BaseModel):
    action: SnapshotAction
    cwd: str | None = Field(default=None, description="Project directory.")
    files: list[str] = Field(
        default_factory=list,
        description="Explicit file paths to snapshot when action='take'.",
    )
    label: str = Field(
        default="", description="Human-readable snapshot label when action='take'."
    )
    snapshot_id: str | None = Field(
        default=None, description="Snapshot ID for action='diff' or action='revert'."
    )
    limit: int = Field(
        default=20, ge=1, description="Number of snapshots to list when action='list'."
    )
    max_age_days: int = Field(
        default=7, ge=1, description="Age threshold for action='cleanup'."
    )

    @model_validator(mode="after")
    def validate_action_requirements(self) -> SnapshotArgs:
        if (
            self.action in {SnapshotAction.DIFF, SnapshotAction.REVERT}
            and not self.snapshot_id
        ):
            raise ValueError(f"snapshot_id is required when action='{self.action}'")
        return self


class SnapshotEntry(BaseModel):
    id: str
    message: str
    timestamp: str


class SnapshotResult(BaseModel):
    action: SnapshotAction
    success: bool
    output: str
    project_dir: str
    snapshot_id: str | None = None
    diff: str | None = None
    reverted_files: list[str] = Field(default_factory=list)
    snapshots: list[SnapshotEntry] = Field(default_factory=list)


class SnapshotToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK


class Snapshot(
    BaseTool[SnapshotArgs, SnapshotResult, SnapshotToolConfig, BaseToolState],
    ToolUIData[SnapshotArgs, SnapshotResult],
):
    description: ClassVar[str] = (
        "Create, inspect, and revert file snapshots stored in Malibu's shadow git repository."
    )

    @classmethod
    def format_call_display(cls, args: SnapshotArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary=f"snapshot {args.action}")

    @classmethod
    def format_result_display(cls, result: SnapshotResult) -> ToolResultDisplay:
        return ToolResultDisplay(success=result.success, message=result.output)

    @classmethod
    def get_status_text(cls) -> str:
        return "Managing snapshots"

    def resolve_permission(self, args: SnapshotArgs) -> ToolPermission | None:
        match args.action:
            case SnapshotAction.REVERT | SnapshotAction.CLEANUP:
                return ToolPermission.ASK
            case _:
                return ToolPermission.ALWAYS

    async def run(
        self, args: SnapshotArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | SnapshotResult, None]:
        del ctx

        cwd = resolve_directory(args.cwd)
        project_dir = snapshot_project_root(cwd)
        manager = SnapshotManager(project_dir)

        match args.action:
            case SnapshotAction.TAKE:
                snapshot_files = self._resolve_snapshot_files(cwd, args.files)
                if not snapshot_files:
                    yield SnapshotResult(
                        action=args.action,
                        success=False,
                        output="Error: no files available to snapshot",
                        project_dir=str(project_dir),
                    )
                    return

                snapshot_id = manager.take_snapshot(
                    [str(path) for path in snapshot_files], label=args.label
                )
                yield SnapshotResult(
                    action=args.action,
                    success=snapshot_id is not None,
                    output=(
                        f"Created snapshot {snapshot_id}"
                        if snapshot_id
                        else "Error: failed to create snapshot"
                    ),
                    project_dir=str(project_dir),
                    snapshot_id=snapshot_id,
                )
            case SnapshotAction.LIST:
                snapshots = [
                    SnapshotEntry.model_validate(item)
                    for item in manager.list_snapshots(limit=args.limit)
                ]
                output = (
                    "\n".join(
                        f"{item.id[:8]} {item.timestamp} {item.message}"
                        for item in snapshots
                    )
                    if snapshots
                    else "(no snapshots)"
                )
                yield SnapshotResult(
                    action=args.action,
                    success=True,
                    output=output,
                    project_dir=str(project_dir),
                    snapshots=snapshots,
                )
            case SnapshotAction.DIFF:
                diff = manager.get_diff(args.snapshot_id or "")
                yield SnapshotResult(
                    action=args.action,
                    success=diff is not None,
                    output=diff
                    or f"Error: failed to diff snapshot '{args.snapshot_id}'",
                    project_dir=str(project_dir),
                    snapshot_id=args.snapshot_id,
                    diff=diff,
                )
            case SnapshotAction.REVERT:
                reverted_files = manager.revert_to_snapshot(args.snapshot_id or "")
                yield SnapshotResult(
                    action=args.action,
                    success=bool(reverted_files),
                    output=(
                        f"Reverted {len(reverted_files)} file(s)"
                        if reverted_files
                        else f"Error: failed to revert snapshot '{args.snapshot_id}'"
                    ),
                    project_dir=str(project_dir),
                    snapshot_id=args.snapshot_id,
                    reverted_files=reverted_files,
                )
            case SnapshotAction.CLEANUP:
                manager.cleanup(max_age_days=args.max_age_days)
                yield SnapshotResult(
                    action=args.action,
                    success=True,
                    output=f"Cleaned snapshots older than {args.max_age_days} day(s)",
                    project_dir=str(project_dir),
                )

    def _resolve_snapshot_files(self, cwd: Path, files: list[str]) -> list[Path]:
        if files:
            resolved_files: list[Path] = []
            for raw_file in files:
                path = Path(raw_file).expanduser()
                resolved = (
                    path.resolve() if path.is_absolute() else (cwd / path).resolve()
                )
                if resolved.exists():
                    resolved_files.append(resolved)
            return resolved_files

        ops = GitOperations(cwd)
        return ops.dirty_files() if ops.repo_root else []
