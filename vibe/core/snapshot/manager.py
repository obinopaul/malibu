"""Git-based snapshot system for reliable file change tracking and revert."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import subprocess

from vibe.core.paths import MALIBU_HOME

logger = logging.getLogger(__name__)


class SnapshotManager:
    """Manages file snapshots using a shadow git repository."""

    def __init__(self, project_dir: Path | str):
        self._project_dir = Path(project_dir).resolve()
        self._project_id = self._compute_project_id()
        self._snapshot_dir = MALIBU_HOME.path / "snapshots" / self._project_id
        self._initialized = False
        self._current_snapshot_id: str | None = None

    @property
    def project_dir(self) -> Path:
        return self._project_dir

    @property
    def snapshot_dir(self) -> Path:
        return self._snapshot_dir

    @property
    def current_snapshot_id(self) -> str | None:
        return self._current_snapshot_id

    def _compute_project_id(self) -> str:
        return hashlib.sha256(str(self._project_dir).encode()).hexdigest()[:16]

    def _ensure_initialized(self) -> bool:
        if self._initialized:
            return True
        try:
            self._snapshot_dir.mkdir(parents=True, exist_ok=True)
            git_dir = self._snapshot_dir / ".git"
            if not git_dir.exists():
                self._git("init")
                self._git("config", "user.name", "malibu-snapshot")
                self._git("config", "user.email", "snapshot@malibu.local")
                self._git("config", "gc.auto", "0")
            self._initialized = True
            return True
        except Exception:
            logger.warning("Failed to initialize snapshot repo", exc_info=True)
            return False

    def take_snapshot(self, files: list[str], label: str = "") -> str | None:
        if not self._ensure_initialized():
            return None

        try:
            copied = 0
            for file_path in files:
                source = Path(file_path)
                if not source.exists():
                    continue

                try:
                    relative_path = source.resolve().relative_to(self._project_dir)
                except ValueError:
                    relative_path = Path(source.name)

                destination = self._snapshot_dir / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
                self._git("add", str(relative_path))
                copied += 1

            if copied == 0:
                return None

            message = f"snapshot: {label}" if label else "snapshot"
            self._git("commit", "-m", message, "--allow-empty")

            snapshot_id = self._git("rev-parse", "HEAD")
            self._current_snapshot_id = snapshot_id.strip() if snapshot_id else None
            return self._current_snapshot_id
        except Exception:
            logger.warning("Failed to take snapshot", exc_info=True)
            return None

    def get_diff(self, snapshot_id: str) -> str | None:
        if not self._ensure_initialized():
            return None

        try:
            result = self._git(
                "diff-tree",
                "--root",
                "--no-commit-id",
                "-r",
                "--name-only",
                snapshot_id,
            )
            if not result:
                return None

            for rel_path in result.strip().splitlines():
                if not rel_path:
                    continue
                source = self._project_dir / rel_path
                destination = self._snapshot_dir / rel_path
                if source.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(source.read_bytes())
                elif destination.exists():
                    destination.unlink()

            return self._git("diff", snapshot_id, "--")
        except Exception:
            logger.warning("Failed to get diff", exc_info=True)
            return None

    def revert_to_snapshot(self, snapshot_id: str) -> list[str]:
        if not self._ensure_initialized():
            return []

        try:
            result = self._git(
                "diff-tree",
                "--root",
                "--no-commit-id",
                "-r",
                "--name-only",
                snapshot_id,
            )
            if not result:
                return []

            reverted: list[str] = []
            for rel_path in result.strip().splitlines():
                if not rel_path:
                    continue
                self._git("checkout", snapshot_id, "--", rel_path)
                source = self._snapshot_dir / rel_path
                destination = self._project_dir / rel_path
                if source.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(source.read_bytes())
                    reverted.append(str(destination))
            return reverted
        except Exception:
            logger.warning("Failed to revert to snapshot", exc_info=True)
            return []

    def list_snapshots(self, limit: int = 20) -> list[dict[str, str]]:
        if not self._ensure_initialized():
            return []

        try:
            result = self._git("log", f"-{limit}", "--format=%H|%s|%ci")
            if not result:
                return []

            snapshots: list[dict[str, str]] = []
            for line in result.strip().splitlines():
                parts = line.split("|", maxsplit=2)
                if len(parts) != 3:
                    continue
                snapshots.append({
                    "id": parts[0],
                    "message": parts[1],
                    "timestamp": parts[2],
                })
            return snapshots
        except Exception:
            logger.warning("Failed to list snapshots", exc_info=True)
            return []

    def cleanup(self, max_age_days: int = 7) -> None:
        if not self._ensure_initialized():
            return
        try:
            self._git("gc", f"--prune={max_age_days}.days.ago")
        except Exception:
            logger.debug("Snapshot GC failed", exc_info=True)

    def _git(self, *args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self._snapshot_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0 and "nothing to commit" not in result.stderr:
                logger.debug("git %s failed: %s", " ".join(args), result.stderr.strip())
                return None
            return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
