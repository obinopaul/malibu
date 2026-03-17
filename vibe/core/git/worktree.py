"""Git worktree management for isolated experiments."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import random
import subprocess

from vibe.core.paths import MALIBU_HOME

logger = logging.getLogger(__name__)

_ADJECTIVES = [
    "swift",
    "bright",
    "calm",
    "bold",
    "keen",
    "warm",
    "cool",
    "deep",
    "fair",
    "fine",
    "glad",
    "pure",
    "safe",
    "wise",
    "neat",
]
_NOUNS = [
    "branch",
    "patch",
    "spike",
    "draft",
    "build",
    "probe",
    "trial",
    "craft",
    "forge",
    "bloom",
    "spark",
    "quest",
    "grove",
    "ridge",
    "haven",
]


def _random_name() -> str:
    """Generate a random adjective-noun worktree name."""
    return f"{random.choice(_ADJECTIVES)}-{random.choice(_NOUNS)}"


@dataclass(frozen=True)
class WorktreeInfo:
    """Information about a git worktree."""

    path: str
    branch: str
    commit: str
    is_main: bool = False

    def __repr__(self) -> str:
        main = " (main)" if self.is_main else ""
        return f"Worktree({self.branch}{main}, {self.path})"


class WorktreeManager:
    """Manages git worktrees for the current project."""

    def __init__(self, repo_dir: Path) -> None:
        self._repo_dir = repo_dir.resolve()
        self._worktree_base = MALIBU_HOME.path / "worktrees"

    @property
    def repo_dir(self) -> Path:
        return self._repo_dir

    @property
    def worktree_base(self) -> Path:
        return self._worktree_base

    def _git(self, *args: str, cwd: str | None = None) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=cwd or str(self._repo_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return None
            return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def create(
        self,
        name: str | None = None,
        branch: str | None = None,
        base_branch: str = "HEAD",
    ) -> WorktreeInfo | None:
        """Create a new worktree."""
        resolved_name = name or _random_name()
        resolved_branch = branch or f"worktree-{resolved_name}"
        worktree_path = self._worktree_base / resolved_name

        try:
            worktree_path.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                [
                    "git",
                    "worktree",
                    "add",
                    "-b",
                    resolved_branch,
                    str(worktree_path),
                    base_branch,
                ],
                cwd=str(self._repo_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning("Failed to create worktree: %s", result.stderr.strip())
                return None

            commit = self._git("rev-parse", "HEAD", cwd=str(worktree_path))
            return WorktreeInfo(
                path=str(worktree_path),
                branch=resolved_branch,
                commit=commit.strip() if commit else "",
                is_main=False,
            )
        except Exception:
            logger.warning("Failed to create worktree", exc_info=True)
            return None

    def list(self) -> list[WorktreeInfo]:
        """List all worktrees for the project."""
        result = self._git("worktree", "list", "--porcelain")
        if not result:
            return []

        worktrees: list[WorktreeInfo] = []
        current: dict[str, str] = {}
        for line in result.splitlines():
            if line.startswith("worktree "):
                if current:
                    worktrees.append(self._parse_worktree(current))
                current = {"path": line.removeprefix("worktree ")}
                continue
            if line.startswith("HEAD "):
                current["commit"] = line.removeprefix("HEAD ")
                continue
            if line.startswith("branch "):
                current["branch"] = line.removeprefix("branch ").replace(
                    "refs/heads/", ""
                )

        if current:
            worktrees.append(self._parse_worktree(current))
        return worktrees

    def remove(self, name: str, force: bool = False) -> bool:
        """Remove a worktree."""
        worktree_path = self._resolve_worktree_path(name)

        cmd = ["git", "worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(str(worktree_path))

        result = subprocess.run(
            cmd,
            cwd=str(self._repo_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("Failed to remove worktree: %s", result.stderr.strip())
            return False
        return True

    def reset(self, name: str) -> bool:
        """Reset a worktree to its branch HEAD."""
        worktree_path = self._resolve_worktree_path(name)
        if not worktree_path.exists():
            return False
        return self._git("reset", "--hard", "HEAD", cwd=str(worktree_path)) is not None

    def get(self, name: str) -> WorktreeInfo | None:
        """Find a worktree by name or path."""
        target = self._resolve_worktree_path(name).resolve()
        for worktree in self.list():
            if Path(worktree.path).resolve() == target:
                return worktree
        return None

    def get_by_name(self, name: str) -> WorktreeInfo | None:
        return self.get(name)

    def _resolve_worktree_path(self, name: str) -> Path:
        candidate = Path(name).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        managed_path = (self._worktree_base / name).resolve()
        return managed_path if managed_path.exists() else candidate.resolve()

    def _parse_worktree(self, data: dict[str, str]) -> WorktreeInfo:
        path = Path(data.get("path", "")).resolve()
        return WorktreeInfo(
            path=str(path),
            branch=data.get("branch", "detached"),
            commit=data.get("commit", ""),
            is_main=path == self._repo_dir,
        )
