"""Safe git operations for the Malibu agent."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import subprocess

logger = logging.getLogger(__name__)

_PROTECTED_BRANCHES = {"main", "master", "develop", "production"}
_PROTECTED_PREFIXES = ("release/",)


@dataclass(frozen=True)
class GitCommitResult:
    success: bool
    output: str
    commit_hash: str | None = None


class GitOperations:
    """Wrapper around common git commands with safety checks."""

    def __init__(self, cwd: str | Path | None = None) -> None:
        raw_cwd = Path(cwd or ".").expanduser()
        self._cwd = raw_cwd.resolve()

    @property
    def cwd(self) -> Path:
        return self._cwd

    @property
    def repo_root(self) -> Path | None:
        result = self._run("rev-parse", "--show-toplevel", timeout=5)
        if result.returncode != 0:
            return None
        root = result.stdout.strip()
        return Path(root).resolve() if root else None

    def _run(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self._cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def is_repo(self) -> bool:
        return self.repo_root is not None

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
        return result.stdout.strip() or "unknown"

    def branches(self) -> list[str]:
        """Return all local branch names."""
        result = self._run("branch", "--format=%(refname:short)")
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line]

    def head(self) -> str | None:
        result = self._run("rev-parse", "HEAD")
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def is_protected_branch(self, branch_name: str | None = None) -> bool:
        """Check if a branch is protected."""
        name = branch_name or self.branch()
        if name in _PROTECTED_BRANCHES:
            return True
        return any(name.startswith(prefix) for prefix in _PROTECTED_PREFIXES)

    def resolve_paths(self, files: list[str]) -> list[Path]:
        base_dir = self.repo_root or self._cwd
        return [
            (Path(file_path).expanduser() if Path(file_path).is_absolute() else base_dir / file_path).resolve()
            for file_path in files
        ]

    def dirty_files(self, *, include_untracked: bool = True) -> list[Path]:
        repo_root = self.repo_root
        if repo_root is None:
            return []

        result = self._run("status", "--porcelain")
        if result.returncode != 0:
            return []

        dirty_paths: list[Path] = []
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            status = line[:2]
            if not include_untracked and status == "??":
                continue

            raw_path = line[3:]
            relative_path = raw_path.split(" -> ")[-1]
            candidate = (repo_root / relative_path).resolve()
            if candidate.exists():
                dirty_paths.append(candidate)

        unique_paths: list[Path] = []
        seen: set[Path] = set()
        for path in dirty_paths:
            if path in seen:
                continue
            seen.add(path)
            unique_paths.append(path)
        return unique_paths

    def has_staged_changes(self) -> bool:
        result = self._run("diff", "--cached", "--quiet", timeout=10)
        return result.returncode == 1

    def commit(self, message: str, files: list[str] | None = None) -> GitCommitResult:
        """Create a git commit. Refuses on protected branches."""
        if self.repo_root is None:
            return GitCommitResult(success=False, output="Error: not a git repository")

        current_branch = self.branch()
        if self.is_protected_branch(current_branch):
            return GitCommitResult(
                success=False,
                output=(
                    "Error: refusing to commit directly to protected branch "
                    f"'{current_branch}'"
                ),
            )

        if files:
            git_paths = self._to_git_paths(files)
            add_result = self._run("add", "--", *git_paths)
            if add_result.returncode != 0:
                return GitCommitResult(
                    success=False,
                    output=f"Error staging files: {add_result.stderr.strip()}",
                )

        if not self.has_staged_changes():
            return GitCommitResult(
                success=False,
                output="Error: no staged changes to commit",
            )

        result = self._run("commit", "-m", message)
        if result.returncode != 0:
            return GitCommitResult(
                success=False,
                output=f"Error: {result.stderr.strip()}",
            )

        return GitCommitResult(
            success=True,
            output=result.stdout.strip() or "Commit created",
            commit_hash=self.head(),
        )

    def context(self) -> str | None:
        if not self.is_repo():
            return None

        branch = self.branch()
        status_output = self.status()
        dirty_count = (
            0
            if status_output == "(clean)"
            else len([line for line in status_output.splitlines() if line.strip()])
        )
        log_output = self.log(n=3, oneline=True)

        parts = [f"Branch: {branch}"]
        if repo_root := self.repo_root:
            parts.append(f"Repository root: {repo_root}")
        if dirty_count:
            parts.append(f"Uncommitted changes: {dirty_count}")
        if log_output and log_output != "(no commits)":
            parts.append(f"Recent commits:\n{log_output}")
        return "\n".join(parts)

    def _to_git_paths(self, files: list[str]) -> list[str]:
        repo_root = self.repo_root or self._cwd
        git_paths: list[str] = []
        for path in self.resolve_paths(files):
            try:
                git_paths.append(str(path.relative_to(repo_root)))
            except ValueError:
                git_paths.append(str(path))
        return git_paths


def get_git_context(cwd: str | Path) -> str | None:
    """Get formatted git context for system prompt injection."""
    try:
        return GitOperations(cwd).context()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
