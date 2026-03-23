"""Git subsystem for Malibu — operations, worktree management, context injection."""

from malibu.git.operations import GitOperations, get_git_context
from malibu.git.worktree import WorktreeManager, WorktreeInfo

__all__ = [
    "GitOperations",
    "get_git_context",
    "WorktreeManager",
    "WorktreeInfo",
]
