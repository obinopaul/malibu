from __future__ import annotations

from collections.abc import AsyncGenerator
from enum import StrEnum, auto
from typing import ClassVar

from pydantic import BaseModel, Field, model_validator

from vibe.core.git import GitOperations
from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolPermission,
)
from vibe.core.tools.builtins._git_support import resolve_directory, snapshot_repo_state
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolStreamEvent


class GitAction(StrEnum):
    CONTEXT = auto()
    STATUS = auto()
    DIFF = auto()
    LOG = auto()
    BRANCH = auto()
    BRANCHES = auto()
    COMMIT = auto()


class GitArgs(BaseModel):
    action: GitAction
    cwd: str | None = Field(default=None, description="Repository directory.")
    staged: bool = Field(
        default=False, description="Use the staged diff when action='diff'."
    )
    n: int = Field(
        default=10, ge=1, description="Number of commits to show when action='log'."
    )
    oneline: bool = Field(
        default=True, description="Use one-line format when action='log'."
    )
    message: str | None = Field(
        default=None, description="Commit message when action='commit'."
    )
    files: list[str] = Field(
        default_factory=list,
        description="Optional file paths to stage before action='commit'.",
    )

    @model_validator(mode="after")
    def validate_action_requirements(self) -> GitArgs:
        if self.action == GitAction.COMMIT and not self.message:
            raise ValueError("message is required when action='commit'")
        return self


class GitResult(BaseModel):
    action: GitAction
    success: bool
    output: str
    repo_root: str | None = None
    branch: str | None = None
    branches: list[str] = Field(default_factory=list)
    commit_hash: str | None = None
    snapshot_id: str | None = None


class GitToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK


class Git(
    BaseTool[GitArgs, GitResult, GitToolConfig, BaseToolState],
    ToolUIData[GitArgs, GitResult],
):
    description: ClassVar[str] = (
        "Inspect repository state and run guarded git commit operations."
    )

    @classmethod
    def format_call_display(cls, args: GitArgs) -> ToolCallDisplay:
        cwd_suffix = f" in {args.cwd}" if args.cwd else ""
        return ToolCallDisplay(summary=f"git {args.action}{cwd_suffix}")

    @classmethod
    def format_result_display(cls, result: GitResult) -> ToolResultDisplay:
        return ToolResultDisplay(success=result.success, message=result.output)

    @classmethod
    def get_status_text(cls) -> str:
        return "Running git"

    def resolve_permission(self, args: GitArgs) -> ToolPermission | None:
        match args.action:
            case GitAction.COMMIT:
                return ToolPermission.ASK
            case _:
                return ToolPermission.ALWAYS

    async def run(
        self, args: GitArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | GitResult, None]:
        del ctx

        cwd = resolve_directory(args.cwd)
        ops = GitOperations(cwd)
        repo_root = ops.repo_root
        branch = ops.branch() if repo_root else None

        match args.action:
            case GitAction.CONTEXT:
                output = ops.context() or "Not a git repository"
                yield GitResult(
                    action=args.action,
                    success=repo_root is not None,
                    output=output,
                    repo_root=str(repo_root) if repo_root else None,
                    branch=branch,
                )
            case GitAction.STATUS:
                output = ops.status()
                yield GitResult(
                    action=args.action,
                    success=not output.startswith("Error:"),
                    output=output,
                    repo_root=str(repo_root) if repo_root else None,
                    branch=branch,
                )
            case GitAction.DIFF:
                output = ops.diff(staged=args.staged)
                yield GitResult(
                    action=args.action,
                    success=not output.startswith("Error:"),
                    output=output,
                    repo_root=str(repo_root) if repo_root else None,
                    branch=branch,
                )
            case GitAction.LOG:
                output = ops.log(n=args.n, oneline=args.oneline)
                yield GitResult(
                    action=args.action,
                    success=not output.startswith("Error:"),
                    output=output,
                    repo_root=str(repo_root) if repo_root else None,
                    branch=branch,
                )
            case GitAction.BRANCH:
                output = branch or "unknown"
                yield GitResult(
                    action=args.action,
                    success=repo_root is not None,
                    output=output,
                    repo_root=str(repo_root) if repo_root else None,
                    branch=branch,
                )
            case GitAction.BRANCHES:
                branches = ops.branches()
                output = "\n".join(branches) if branches else "(no branches)"
                yield GitResult(
                    action=args.action,
                    success=repo_root is not None,
                    output=output,
                    repo_root=str(repo_root) if repo_root else None,
                    branch=branch,
                    branches=branches,
                )
            case GitAction.COMMIT:
                _, snapshot_id = snapshot_repo_state(
                    ops, label="before git commit", files=args.files or None
                )
                commit_result = ops.commit(args.message or "", args.files or None)
                yield GitResult(
                    action=args.action,
                    success=commit_result.success,
                    output=commit_result.output,
                    repo_root=str(repo_root) if repo_root else None,
                    branch=branch,
                    commit_hash=commit_result.commit_hash,
                    snapshot_id=snapshot_id,
                )
