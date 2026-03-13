"""Git-based snapshot system for reliable file change tracking and revert.

Uses a shadow git repository to create atomic snapshots of modified files
before and after tool execution. This enables reliable revert of any
change set, regardless of complexity.

Adapted from OpenDev's snapshot system.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from malibu.telemetry.logging import get_logger

_log = get_logger(__name__)


class SnapshotManager:
    """Manages file snapshots using a shadow git repository.

    Each project gets its own shadow git repository stored at
    ``~/.malibu/snapshots/{project_id}`` where project_id is a hash
    of the project path.

    Usage:
        manager = SnapshotManager(project_dir)
        snapshot_id = manager.take_snapshot(["/path/to/file.py"], "before edit")
        # ... make changes ...
        diff = manager.get_diff(snapshot_id)
        manager.revert_to_snapshot(snapshot_id)  # undo changes
    """

    def __init__(self, project_dir: Path | str):
        """Initialize snapshot manager for a project.

        Args:
            project_dir: Root directory of the project to snapshot.
        """
        self._project_dir = Path(project_dir).resolve()
        self._project_id = self._compute_project_id()
        self._snapshot_dir = (
            Path.home() / ".malibu" / "snapshots" / self._project_id
        )
        self._initialized = False
        self._current_snapshot_id: str | None = None

    def _compute_project_id(self) -> str:
        """Compute a stable project identifier from the project path."""
        return hashlib.sha256(str(self._project_dir).encode()).hexdigest()[:16]

    @property
    def project_dir(self) -> Path:
        """Return the project root directory."""
        return self._project_dir

    @property
    def snapshot_dir(self) -> Path:
        """Return the snapshot repository directory."""
        return self._snapshot_dir

    @property
    def current_snapshot_id(self) -> str | None:
        """Return the most recent snapshot ID."""
        return self._current_snapshot_id

    def _ensure_initialized(self) -> bool:
        """Initialize the shadow git repo if needed.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._initialized:
            return True
        try:
            self._snapshot_dir.mkdir(parents=True, exist_ok=True)
            git_dir = self._snapshot_dir / ".git"
            if not git_dir.exists():
                self._git("init")
                # Configure for snapshot use
                self._git("config", "user.name", "malibu-snapshot")
                self._git("config", "user.email", "snapshot@malibu.local")
                self._git("config", "gc.auto", "0")  # Manual GC only
            self._initialized = True
            return True
        except Exception:
            _log.warning("snapshot_init_failed", project=str(self._project_dir))
            return False

    def take_snapshot(self, files: list[str], label: str = "") -> str | None:
        """Take a snapshot of the given files before modification.

        Copies the specified files into the shadow git repository and
        creates a commit. The commit hash serves as the snapshot ID.

        Args:
            files: List of absolute file paths to snapshot.
            label: Human-readable label for the snapshot.

        Returns:
            Snapshot ID (git commit hash) or None on failure.
        """
        if not self._ensure_initialized():
            return None

        try:
            # Copy files into snapshot repo
            copied = 0
            for file_path in files:
                src = Path(file_path)
                if not src.exists():
                    continue
                # Compute relative path from project root
                try:
                    rel = src.relative_to(self._project_dir)
                except ValueError:
                    rel = Path(src.name)
                dest = self._snapshot_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(src.read_bytes())
                self._git("add", str(rel))
                copied += 1

            if copied == 0:
                return None

            # Commit snapshot
            msg = f"snapshot: {label}" if label else "snapshot"
            self._git("commit", "-m", msg, "--allow-empty")

            # Get commit hash
            result = self._git("rev-parse", "HEAD")
            snapshot_id = result.strip() if result else None
            self._current_snapshot_id = snapshot_id

            _log.debug(
                "snapshot_created",
                snapshot_id=snapshot_id[:8] if snapshot_id else "?",
                files=copied,
                label=label,
            )
            return snapshot_id

        except Exception:
            _log.warning("snapshot_failed", exc_info=True)
            return None

    def get_diff(self, snapshot_id: str) -> str | None:
        """Get diff between a snapshot and the current project state.

        Args:
            snapshot_id: The snapshot commit hash to diff against.

        Returns:
            Unified diff string or None.
        """
        if not self._ensure_initialized():
            return None

        try:
            # Get files from snapshot
            result = self._git(
                "diff-tree", "--no-commit-id", "-r", "--name-only", snapshot_id
            )
            if not result:
                return None

            files = result.strip().split("\n")
            for rel_path in files:
                if not rel_path.strip():
                    continue
                src = self._project_dir / rel_path
                dest = self._snapshot_dir / rel_path
                if src.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(src.read_bytes())
                elif dest.exists():
                    dest.unlink()

            # Generate diff
            diff = self._git("diff", snapshot_id, "--")
            return diff

        except Exception:
            _log.warning("snapshot_diff_failed", exc_info=True)
            return None

    def revert_to_snapshot(self, snapshot_id: str) -> list[str]:
        """Revert project files to a snapshot state.

        Args:
            snapshot_id: The snapshot commit hash to revert to.

        Returns:
            List of reverted file paths (absolute paths).
        """
        if not self._ensure_initialized():
            return []

        try:
            # Get files from snapshot
            result = self._git(
                "diff-tree", "--no-commit-id", "-r", "--name-only", snapshot_id
            )
            if not result:
                return []

            reverted = []
            files = result.strip().split("\n")
            for rel_path in files:
                if not rel_path.strip():
                    continue
                # Checkout file from snapshot into snapshot dir
                self._git("checkout", snapshot_id, "--", rel_path)
                # Copy back to project
                src = self._snapshot_dir / rel_path
                dest = self._project_dir / rel_path
                if src.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(src.read_bytes())
                    reverted.append(str(dest))

            _log.info(
                "snapshot_reverted",
                snapshot_id=snapshot_id[:8],
                files=len(reverted),
            )
            return reverted

        except Exception:
            _log.warning("snapshot_revert_failed", exc_info=True)
            return []

    def list_snapshots(self, limit: int = 20) -> list[dict[str, str]]:
        """List recent snapshots.

        Args:
            limit: Maximum number of snapshots to return.

        Returns:
            List of dicts with 'id', 'message', 'timestamp' keys.
        """
        if not self._ensure_initialized():
            return []

        try:
            result = self._git(
                "log",
                f"-{limit}",
                "--format=%H|%s|%ci",
            )
            if not result:
                return []

            snapshots = []
            for line in result.strip().split("\n"):
                if "|" not in line:
                    continue
                parts = line.split("|", 2)
                if len(parts) < 3:
                    continue
                snapshots.append({
                    "id": parts[0],
                    "message": parts[1],
                    "timestamp": parts[2],
                })
            return snapshots

        except Exception:
            return []

    def cleanup(self, max_age_days: int = 7) -> None:
        """Run garbage collection on the snapshot repo.

        Args:
            max_age_days: Prune commits older than this many days.
        """
        if not self._ensure_initialized():
            return
        try:
            self._git("gc", f"--prune={max_age_days}.days.ago")
            _log.debug("snapshot_gc_complete", max_age_days=max_age_days)
        except Exception:
            _log.debug("snapshot_gc_failed", exc_info=True)

    def _git(self, *args: str) -> str | None:
        """Run a git command in the snapshot directory.

        Args:
            *args: Git subcommand and arguments.

        Returns:
            Stdout on success, None on failure.
        """
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(self._snapshot_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0 and "nothing to commit" not in result.stderr:
                _log.debug(
                    "git_command_failed",
                    cmd=" ".join(args),
                    stderr=result.stderr.strip(),
                )
                return None
            return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
