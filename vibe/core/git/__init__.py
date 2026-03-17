"""Git subsystem for Malibu — operations, worktree management, context injection."""

from vibe.core.git.operations import GitOperations, get_git_context
from vibe.core.git.worktree import WorktreeManager, WorktreeInfo

__all__ = [
    "GitOperations",
    "get_git_context",
    "WorktreeManager",
    "WorktreeInfo",
]
