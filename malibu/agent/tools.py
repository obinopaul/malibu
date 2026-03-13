"""Tool definitions for the Malibu agent.

Each tool uses the ``@tool`` decorator from ``langchain_core.tools``.
The ``create_agent()`` call binds them automatically — no manual ToolNode needed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


# ═══════════════════════════════════════════════════════════════════
# Filesystem tools
# ═══════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════
# Plan / TODO management
# ═══════════════════════════════════════════════════════════════════
@tool
def write_todos(todos: list[dict[str, str]]) -> str:
    """Create or update the execution plan.

    The plan will be displayed to the user in the plan panel.  The user must
    approve the plan before the assistant begins executing it.

    Args:
        todos: List of dicts with 'content' and 'status' keys.
               Status is one of 'pending', 'in_progress', 'completed'.
    """
    # Format the plan for display; the server streaming loop also intercepts
    # write_todos calls and forwards them to the client as AgentPlanUpdate.
    lines = []
    for i, item in enumerate(todos, 1):
        status = item.get("status", "pending")
        content = item.get("content", "")
        icon = {"completed": "✓", "in_progress": "→", "pending": "○"}.get(status, "○")
        lines.append(f"  {icon} {i}. {content} [{status}]")
    plan_text = "Plan updated:\n" + "\n".join(lines)
    return plan_text


# ═══════════════════════════════════════════════════════════════════
# Git tools
# ═══════════════════════════════════════════════════════════════════

@tool
def git_status(cwd: str | None = None) -> str:
    """Show the git status of the working directory.

    Args:
        cwd: Working directory. Defaults to the session cwd.
    """
    from malibu.git.operations import GitOperations
    return GitOperations(cwd).status()


@tool
def git_diff(staged: bool = False, cwd: str | None = None) -> str:
    """Show the git diff (unstaged or staged changes).

    Args:
        staged: If True, show staged changes. Defaults to unstaged.
        cwd: Working directory.
    """
    from malibu.git.operations import GitOperations
    return GitOperations(cwd).diff(staged=staged)


@tool
def git_log(n: int = 10, cwd: str | None = None) -> str:
    """Show recent git commit history.

    Args:
        n: Number of commits to show.
        cwd: Working directory.
    """
    from malibu.git.operations import GitOperations
    return GitOperations(cwd).log(n=n)


@tool
def git_commit(message: str, files: list[str] | None = None, cwd: str | None = None) -> str:
    """Create a git commit. Refuses on protected branches (main, master, develop, production).

    Args:
        message: Commit message.
        files: Files to stage before committing. If None, commits whatever is staged.
        cwd: Working directory.
    """
    from malibu.git.operations import GitOperations
    return GitOperations(cwd).commit(message, files=files)


@tool
def git_worktree_create(name: str | None = None, branch: str | None = None, cwd: str | None = None) -> str:
    """Create a new git worktree for isolated work.

    Args:
        name: Worktree name (auto-generated if omitted).
        branch: Branch name (defaults to worktree-{name}).
        cwd: Repository directory.
    """
    from malibu.git.worktree import WorktreeManager
    mgr = WorktreeManager(Path(cwd or "."))
    info = mgr.create(name=name, branch=branch)
    if info is None:
        return "Error: failed to create worktree"
    return f"Created worktree '{info.branch}' at {info.path}"


@tool
def git_worktree_list(cwd: str | None = None) -> str:
    """List all git worktrees for the repository.

    Args:
        cwd: Repository directory.
    """
    from malibu.git.worktree import WorktreeManager
    mgr = WorktreeManager(Path(cwd or "."))
    worktrees = mgr.list()
    if not worktrees:
        return "(no worktrees)"
    lines = [f"{wt.branch} -> {wt.path}" for wt in worktrees]
    return "\n".join(lines)


@tool
def git_worktree_remove(name: str, force: bool = False, cwd: str | None = None) -> str:
    """Remove a git worktree.

    Args:
        name: Worktree name or path.
        force: Force removal even with uncommitted changes.
        cwd: Repository directory.
    """
    from malibu.git.worktree import WorktreeManager
    mgr = WorktreeManager(Path(cwd or "."))
    ok = mgr.remove(name, force=force)
    return f"Worktree '{name}' removed" if ok else f"Error: failed to remove worktree '{name}'"


GIT_TOOLS = [git_status, git_diff, git_log, git_commit, git_worktree_create, git_worktree_list, git_worktree_remove]


# ═══════════════════════════════════════════════════════════════════
# Collected tool list
# ═══════════════════════════════════════════════════════════════════
ALL_TOOLS = [write_todos]

# Conditionally add git tools if git is available
import shutil
if shutil.which("git"):
    ALL_TOOLS.extend(GIT_TOOLS)
