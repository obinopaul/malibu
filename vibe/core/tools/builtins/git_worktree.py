from __future__ import annotations

from collections.abc import AsyncGenerator
from enum import StrEnum, auto
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field, model_validator

from vibe.core.git import GitOperations, WorktreeInfo, WorktreeManager
from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolPermission,
)
from vibe.core.tools.builtins._git_support import (
    resolve_directory,
    snapshot_repo_state,
    snapshot_worktree_state,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolStreamEvent


class GitWorktreeAction(StrEnum):
    LIST = auto()
    GET = auto()
    CREATE = auto()
    REMOVE = auto()
    RESET = auto()


class GitWorktreeArgs(BaseModel):
    action: GitWorktreeAction
    cwd: str | None = Field(default=None, description="Repository directory.")
    name: str | None = Field(
        default=None,
        description="Managed worktree name or absolute worktree path.",
    )
    branch: str | None = Field(
        default=None,
        description="Branch name when action='create'.",
    )
    base_branch: str = Field(
        default="HEAD",
        description="Starting ref when action='create'.",
    )
    force: bool = Field(
        default=False,
        description="Force removal when action='remove'.",
    )

    @model_validator(mode="after")
    def validate_action_requirements(self) -> GitWorktreeArgs:
        if self.action in {
            GitWorktreeAction.GET,
            GitWorktreeAction.REMOVE,
            GitWorktreeAction.RESET,
        } and not self.name:
            raise ValueError(f"name is required when action='{self.action}'")
        return self


class GitWorktreeItem(BaseModel):
    path: str
    branch: str
    commit: str
    is_main: bool = False

    @classmethod
    def from_info(cls, info: WorktreeInfo) -> GitWorktreeItem:
        return cls(
            path=info.path,
            branch=info.branch,
            commit=info.commit,
            is_main=info.is_main,
        )


class GitWorktreeResult(BaseModel):
    action: GitWorktreeAction
    success: bool
    output: str
    snapshot_id: str | None = None
    worktree: GitWorktreeItem | None = None
    worktrees: list[GitWorktreeItem] = Field(default_factory=list)


class GitWorktreeToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK


class GitWorktree(
    BaseTool[GitWorktreeArgs, GitWorktreeResult, GitWorktreeToolConfig, BaseToolState],
    ToolUIData[GitWorktreeArgs, GitWorktreeResult],
):
    description: ClassVar[str] = (
        "Inspect and manage git worktrees for isolated branches."
    )

    @classmethod
    def format_call_display(cls, args: GitWorktreeArgs) -> ToolCallDisplay:
        target = f" {args.name}" if args.name else ""
        return ToolCallDisplay(summary=f"git_worktree {args.action}{target}")

    @classmethod
    def format_result_display(cls, result: GitWorktreeResult) -> ToolResultDisplay:
        return ToolResultDisplay(success=result.success, message=result.output)

    @classmethod
    def get_status_text(cls) -> str:
        return "Managing Git worktrees"

    def resolve_permission(self, args: GitWorktreeArgs) -> ToolPermission | None:
        match args.action:
            case GitWorktreeAction.LIST | GitWorktreeAction.GET:
                return ToolPermission.ALWAYS
            case _:
                return ToolPermission.ASK

    async def run(
        self, args: GitWorktreeArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | GitWorktreeResult, None]:
        del ctx

        cwd = resolve_directory(args.cwd)
        manager = WorktreeManager(cwd)

        match args.action:
            case GitWorktreeAction.LIST:
                worktrees = [
                    GitWorktreeItem.from_info(info) for info in manager.list()
                ]
                output = (
                    "\n".join(f"{item.branch} -> {item.path}" for item in worktrees)
                    if worktrees
                    else "(no worktrees)"
                )
                yield GitWorktreeResult(
                    action=args.action,
                    success=True,
                    output=output,
                    worktrees=worktrees,
                )
            case GitWorktreeAction.GET:
                info = manager.get(args.name or "")
                if info is None:
                    yield GitWorktreeResult(
                        action=args.action,
                        success=False,
                        output=f"Error: worktree '{args.name}' not found",
                    )
                    return
                item = GitWorktreeItem.from_info(info)
                yield GitWorktreeResult(
                    action=args.action,
                    success=True,
                    output=f"{item.branch} -> {item.path}",
                    worktree=item,
                )
            case GitWorktreeAction.CREATE:
                _, snapshot_id = snapshot_repo_state(
                    ops=GitOperations(cwd),
                    label="before git_worktree create",
                )
                info = manager.create(
                    name=args.name,
                    branch=args.branch,
                    base_branch=args.base_branch,
                )
                if info is None:
                    yield GitWorktreeResult(
                        action=args.action,
                        success=False,
                        output="Error: failed to create worktree",
                        snapshot_id=snapshot_id,
                    )
                    return
                item = GitWorktreeItem.from_info(info)
                yield GitWorktreeResult(
                    action=args.action,
                    success=True,
                    output=f"Created worktree '{item.branch}' at {item.path}",
                    snapshot_id=snapshot_id,
                    worktree=item,
                )
            case GitWorktreeAction.REMOVE:
                info = manager.get(args.name or "")
                if info is None:
                    yield GitWorktreeResult(
                        action=args.action,
                        success=False,
                        output=f"Error: worktree '{args.name}' not found",
                    )
                    return
                snapshot_id = snapshot_worktree_state(
                    Path(info.path),
                    label="before git_worktree remove",
                )
                success = manager.remove(args.name or "", force=args.force)
                output = (
                    f"Worktree '{args.name}' removed"
                    if success
                    else f"Error: failed to remove worktree '{args.name}'"
                )
                yield GitWorktreeResult(
                    action=args.action,
                    success=success,
                    output=output,
                    snapshot_id=snapshot_id,
                )
            case GitWorktreeAction.RESET:
                info = manager.get(args.name or "")
                if info is None:
                    yield GitWorktreeResult(
                        action=args.action,
                        success=False,
                        output=f"Error: worktree '{args.name}' not found",
                    )
                    return
                snapshot_id = snapshot_worktree_state(
                    Path(info.path),
                    label="before git_worktree reset",
                )
                success = manager.reset(args.name or "")
                output = (
                    f"Worktree '{args.name}' reset to HEAD"
                    if success
                    else f"Error: failed to reset worktree '{args.name}'"
                )
                yield GitWorktreeResult(
                    action=args.action,
                    success=success,
                    output=output,
                    snapshot_id=snapshot_id,
                )
