from __future__ import annotations

from pathlib import Path

from vibe.core.git import GitOperations
from vibe.core.snapshot import SnapshotManager
from vibe.core.tools.base import ToolError


def resolve_directory(raw_cwd: str | None) -> Path:
    candidate = Path(raw_cwd or Path.cwd()).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise ToolError(f"Invalid directory: {candidate}") from exc

    if not resolved.exists():
        raise ToolError(f"Directory does not exist: {resolved}")
    if not resolved.is_dir():
        raise ToolError(f"Path is not a directory: {resolved}")
    return resolved


def snapshot_repo_state(
    ops: GitOperations,
    *,
    label: str,
    files: list[str] | None = None,
) -> tuple[Path | None, str | None]:
    repo_root = ops.repo_root
    if repo_root is None:
        return None, None

    snapshot_files = (
        [path for path in ops.resolve_paths(files) if path.exists()]
        if files
        else ops.dirty_files()
    )
    if not snapshot_files:
        return repo_root, None

    snapshot_id = SnapshotManager(repo_root).take_snapshot(
        [str(path) for path in snapshot_files],
        label=label,
    )
    return repo_root, snapshot_id


def snapshot_worktree_state(worktree_path: Path, *, label: str) -> str | None:
    ops = GitOperations(worktree_path)
    snapshot_files = ops.dirty_files()
    if not snapshot_files:
        return None
    return SnapshotManager(worktree_path).take_snapshot(
        [str(path) for path in snapshot_files],
        label=label,
    )


def snapshot_project_root(cwd: Path) -> Path:
    return GitOperations(cwd).repo_root or cwd
