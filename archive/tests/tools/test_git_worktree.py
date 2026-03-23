from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tests.mock.utils import collect_result
from vibe.core.tools.base import BaseToolState
from vibe.core.tools.builtins.git_worktree import (
    GitWorktree,
    GitWorktreeAction,
    GitWorktreeArgs,
    GitWorktreeToolConfig,
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
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


@pytest.fixture
def worktree_tool() -> GitWorktree:
    return GitWorktree(config=GitWorktreeToolConfig(), state=BaseToolState())


@pytest.mark.asyncio
async def test_git_worktree_tool_lists_gets_and_resets_with_snapshot_id(
    worktree_tool: GitWorktree, tmp_path: Path
) -> None:
    repo = _init_repo(tmp_path)
    (repo / "README.md").write_text("initial\nunsaved root change\n", encoding="utf-8")

    created = await collect_result(
        worktree_tool.run(
            GitWorktreeArgs(
                action=GitWorktreeAction.CREATE,
                cwd=str(repo),
                name="planner-wt",
                branch="feature/worktree-test",
            )
        )
    )

    assert created.success is True
    assert created.snapshot_id is not None
    assert created.worktree is not None

    listed = await collect_result(
        worktree_tool.run(GitWorktreeArgs(action=GitWorktreeAction.LIST, cwd=str(repo)))
    )
    fetched = await collect_result(
        worktree_tool.run(
            GitWorktreeArgs(
                action=GitWorktreeAction.GET, cwd=str(repo), name="planner-wt"
            )
        )
    )

    assert any(item.branch == "feature/worktree-test" for item in listed.worktrees)
    assert fetched.worktree is not None

    worktree_path = Path(fetched.worktree.path)
    (worktree_path / "README.md").write_text(
        "initial\nworktree change\n", encoding="utf-8"
    )

    reset = await collect_result(
        worktree_tool.run(
            GitWorktreeArgs(
                action=GitWorktreeAction.RESET, cwd=str(repo), name="planner-wt"
            )
        )
    )

    assert reset.success is True
    assert reset.snapshot_id is not None
    assert (worktree_path / "README.md").read_text(encoding="utf-8") == "initial\n"


@pytest.mark.asyncio
async def test_git_worktree_tool_removes_worktree_and_returns_snapshot_id(
    worktree_tool: GitWorktree, tmp_path: Path
) -> None:
    repo = _init_repo(tmp_path)
    created = await collect_result(
        worktree_tool.run(
            GitWorktreeArgs(
                action=GitWorktreeAction.CREATE,
                cwd=str(repo),
                name="cleanup-wt",
                branch="feature/remove-worktree",
            )
        )
    )

    assert created.success is True
    assert created.worktree is not None

    worktree_path = Path(created.worktree.path)
    (worktree_path / "README.md").write_text("initial\nremove me\n", encoding="utf-8")

    removed = await collect_result(
        worktree_tool.run(
            GitWorktreeArgs(
                action=GitWorktreeAction.REMOVE,
                cwd=str(repo),
                name="cleanup-wt",
                force=True,
            )
        )
    )

    assert removed.success is True
    assert removed.snapshot_id is not None
    assert worktree_path.exists() is False
