from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tests.mock.utils import collect_result
from vibe.core.tools.base import BaseToolState
from vibe.core.tools.builtins.git import Git, GitAction, GitArgs, GitToolConfig


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
def git_tool() -> Git:
    return Git(config=GitToolConfig(), state=BaseToolState())


@pytest.mark.asyncio
async def test_git_tool_reports_repository_state(git_tool: Git, tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "switch", "-c", "feature/test-git")
    (repo / "README.md").write_text("initial\nchange\n", encoding="utf-8")

    status = await collect_result(
        git_tool.run(GitArgs(action=GitAction.STATUS, cwd=str(repo)))
    )
    diff = await collect_result(
        git_tool.run(GitArgs(action=GitAction.DIFF, cwd=str(repo)))
    )
    log = await collect_result(
        git_tool.run(GitArgs(action=GitAction.LOG, cwd=str(repo), n=2))
    )
    branch = await collect_result(
        git_tool.run(GitArgs(action=GitAction.BRANCH, cwd=str(repo)))
    )
    branches = await collect_result(
        git_tool.run(GitArgs(action=GitAction.BRANCHES, cwd=str(repo)))
    )
    context = await collect_result(
        git_tool.run(GitArgs(action=GitAction.CONTEXT, cwd=str(repo)))
    )

    assert "README.md" in status.output
    assert "change" in diff.output
    assert "initial" in log.output
    assert branch.output == "feature/test-git"
    assert "main" in branches.branches
    assert "feature/test-git" in branches.branches
    assert "Branch: feature/test-git" in context.output
    assert "Repository root:" in context.output


@pytest.mark.asyncio
async def test_git_tool_refuses_commit_on_protected_branch_and_returns_snapshot_id(
    git_tool: Git, tmp_path: Path
) -> None:
    repo = _init_repo(tmp_path)
    (repo / "README.md").write_text("initial\nblocked\n", encoding="utf-8")

    result = await collect_result(
        git_tool.run(
            GitArgs(action=GitAction.COMMIT, cwd=str(repo), message="blocked commit")
        )
    )

    assert result.success is False
    assert "protected branch" in result.output
    assert result.snapshot_id is not None


@pytest.mark.asyncio
async def test_git_tool_commits_on_feature_branch_and_returns_snapshot_id(
    git_tool: Git, tmp_path: Path
) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "switch", "-c", "feature/commit-test")
    (repo / "README.md").write_text("initial\nfeature work\n", encoding="utf-8")
    _git(repo, "add", "README.md")

    result = await collect_result(
        git_tool.run(
            GitArgs(action=GitAction.COMMIT, cwd=str(repo), message="feature commit")
        )
    )

    assert result.success is True
    assert result.commit_hash is not None
    assert result.commit_hash == _git(repo, "rev-parse", "HEAD")
