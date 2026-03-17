from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tests.mock.utils import collect_result
from vibe.core.snapshot import SnapshotManager
from vibe.core.tools.base import BaseToolState
from vibe.core.tools.builtins.snapshot import (
    Snapshot,
    SnapshotAction,
    SnapshotArgs,
    SnapshotToolConfig,
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, check=True, text=True
    )
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "branch", "-M", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    src_dir = repo / "src"
    src_dir.mkdir()
    (src_dir / "module.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "src/module.py")
    _git(repo, "commit", "-m", "initial")
    return repo


@pytest.fixture
def snapshot_tool() -> Snapshot:
    return Snapshot(config=SnapshotToolConfig(), state=BaseToolState())


@pytest.mark.asyncio
async def test_snapshot_tool_takes_lists_diffs_reverts_and_cleans_up(
    snapshot_tool: Snapshot, tmp_path: Path
) -> None:
    repo = _init_repo(tmp_path)
    tracked_file = repo / "src" / "module.py"
    tracked_file.write_text("value = 2\n", encoding="utf-8")

    taken = await collect_result(
        snapshot_tool.run(
            SnapshotArgs(
                action=SnapshotAction.TAKE, cwd=str(repo), label="before refactor"
            )
        )
    )

    assert taken.success is True
    assert taken.snapshot_id is not None

    listed = await collect_result(
        snapshot_tool.run(
            SnapshotArgs(action=SnapshotAction.LIST, cwd=str(repo), limit=5)
        )
    )

    assert any(item.id == taken.snapshot_id for item in listed.snapshots)

    tracked_file.write_text("value = 3\n", encoding="utf-8")

    diffed = await collect_result(
        snapshot_tool.run(
            SnapshotArgs(
                action=SnapshotAction.DIFF, cwd=str(repo), snapshot_id=taken.snapshot_id
            )
        )
    )

    assert diffed.success is True
    assert diffed.diff is not None
    assert "src/module.py" in diffed.diff

    reverted = await collect_result(
        snapshot_tool.run(
            SnapshotArgs(
                action=SnapshotAction.REVERT,
                cwd=str(repo),
                snapshot_id=taken.snapshot_id,
            )
        )
    )

    assert reverted.success is True
    assert str(tracked_file) in reverted.reverted_files
    assert tracked_file.read_text(encoding="utf-8") == "value = 2\n"

    cleaned = await collect_result(
        snapshot_tool.run(
            SnapshotArgs(action=SnapshotAction.CLEANUP, cwd=str(repo), max_age_days=1)
        )
    )

    assert cleaned.success is True


def test_snapshot_manager_tracks_current_snapshot_and_repo_relative_paths(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    tracked_file = repo / "src" / "module.py"
    tracked_file.write_text("value = 2\n", encoding="utf-8")

    manager = SnapshotManager(repo)
    snapshot_id = manager.take_snapshot([str(tracked_file)], label="tracked file")

    assert snapshot_id is not None
    assert manager.current_snapshot_id == snapshot_id
    assert (manager.snapshot_dir / "src" / "module.py").exists()
