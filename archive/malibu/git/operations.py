"""Safe git operations for the Malibu agent."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_PROTECTED_BRANCHES = {"main", "master", "develop", "production"}
_PROTECTED_PREFIXES = ("release/",)


class GitOperations:
    """Wrapper around common git commands with safety checks."""

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = cwd or "."

    def _run(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self._cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def status(self) -> str:
        """Return short git status."""
        result = self._run("status", "--short")
        if result.returncode != 0:
            return f"Error: {result.stderr.strip()}"
        return result.stdout.strip() or "(clean)"

    def diff(self, staged: bool = False) -> str:
        """Return git diff output."""
        args = ["diff", "--staged"] if staged else ["diff"]
        result = self._run(*args)
        if result.returncode != 0:
            return f"Error: {result.stderr.strip()}"
        return result.stdout.strip() or "(no changes)"

    def log(self, n: int = 10, oneline: bool = True) -> str:
        """Return recent git log."""
        args = ["log", f"-{n}"]
        if oneline:
            args.append("--oneline")
        result = self._run(*args)
        if result.returncode != 0:
            return f"Error: {result.stderr.strip()}"
        return result.stdout.strip() or "(no commits)"

    def branch(self) -> str:
        """Return current branch name."""
        result = self._run("rev-parse", "--abbrev-ref", "HEAD")
        if result.returncode != 0:
            return "unknown"
        return result.stdout.strip()

    def branches(self) -> list[str]:
        """Return all local branch names."""
        result = self._run("branch", "--format=%(refname:short)")
        if result.returncode != 0:
            return []
        return [b for b in result.stdout.strip().splitlines() if b]

    def is_protected_branch(self, branch_name: str | None = None) -> bool:
        """Check if a branch is protected."""
        name = branch_name or self.branch()
        if name in _PROTECTED_BRANCHES:
            return True
        return any(name.startswith(p) for p in _PROTECTED_PREFIXES)

    def commit(self, message: str, files: list[str] | None = None) -> str:
        """Create a git commit. Refuses on protected branches.

        Args:
            message: Commit message.
            files: Files to stage. If None, commits whatever is already staged.

        Returns:
            Success or error message.
        """
        current = self.branch()
        if self.is_protected_branch(current):
            return f"Error: refusing to commit directly to protected branch '{current}'"

        if files:
            add_result = self._run("add", "--", *files)
            if add_result.returncode != 0:
                return f"Error staging files: {add_result.stderr.strip()}"

        result = self._run("commit", "-m", message)
        if result.returncode != 0:
            return f"Error: {result.stderr.strip()}"
        return result.stdout.strip()


def get_git_context(cwd: str) -> str | None:
    """Get formatted git context for system prompt injection.

    Returns None if not in a git repo.
    """
    try:
        ops = GitOperations(cwd)
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd, capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None

        branch = ops.branch()
        status_output = ops.status()

        # Count uncommitted changes
        lines = [l for l in status_output.splitlines() if l.strip()] if status_output != "(clean)" else []
        uncommitted = len(lines)

        log_output = ops.log(n=3, oneline=True)

        parts = [f"Branch: {branch}"]
        if uncommitted:
            parts.append(f"Uncommitted changes: {uncommitted}")
        if log_output and log_output != "(no commits)":
            parts.append(f"Recent commits:\n{log_output}")

        return "\n".join(parts)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
