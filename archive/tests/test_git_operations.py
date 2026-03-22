"""Tests for malibu.git.operations and malibu.git.worktree."""

import subprocess
import tempfile
from pathlib import Path

import pytest

from malibu.git.operations import GitOperations, get_git_context
from malibu.git.worktree import WorktreeManager, WorktreeInfo


@pytest.fixture
def git_repo():
    """Create a temporary git repo with one commit."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "init", tmp], capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True)
        # Create initial commit
        readme = Path(tmp) / "README.md"
        readme.write_text("# Test\n")
        subprocess.run(["git", "add", "README.md"], cwd=tmp, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmp, capture_output=True)
        yield tmp


class TestGitOperations:
    def test_status_clean(self, git_repo: str) -> None:
        ops = GitOperations(git_repo)
        assert ops.status() == "(clean)"

    def test_status_dirty(self, git_repo: str) -> None:
        (Path(git_repo) / "new.txt").write_text("hello")
        ops = GitOperations(git_repo)
        result = ops.status()
        assert "new.txt" in result

    def test_diff_no_changes(self, git_repo: str) -> None:
        ops = GitOperations(git_repo)
        assert ops.diff() == "(no changes)"

    def test_diff_with_changes(self, git_repo: str) -> None:
        readme = Path(git_repo) / "README.md"
        readme.write_text("# Updated\n")
        ops = GitOperations(git_repo)
        result = ops.diff()
        assert "Updated" in result

    def test_log(self, git_repo: str) -> None:
        ops = GitOperations(git_repo)
        result = ops.log(n=5)
        assert "Initial commit" in result

    def test_branch(self, git_repo: str) -> None:
        ops = GitOperations(git_repo)
        branch = ops.branch()
        assert branch in ("main", "master")

    def test_branches(self, git_repo: str) -> None:
        ops = GitOperations(git_repo)
        branches = ops.branches()
        assert len(branches) >= 1

    def test_is_protected_branch(self, git_repo: str) -> None:
        ops = GitOperations(git_repo)
        assert ops.is_protected_branch("main") is True
        assert ops.is_protected_branch("master") is True
        assert ops.is_protected_branch("develop") is True
        assert ops.is_protected_branch("production") is True
        assert ops.is_protected_branch("release/v1.0") is True
        assert ops.is_protected_branch("feature/foo") is False

    def test_commit_on_feature_branch(self, git_repo: str) -> None:
        subprocess.run(["git", "checkout", "-b", "feature/test"], cwd=git_repo, capture_output=True)
        (Path(git_repo) / "new.txt").write_text("content")
        ops = GitOperations(git_repo)
        result = ops.commit("Add new file", files=["new.txt"])
        assert "Error" not in result

    def test_commit_refuses_on_protected(self, git_repo: str) -> None:
        ops = GitOperations(git_repo)
        result = ops.commit("Bad commit")
        assert "protected branch" in result


class TestGetGitContext:
    def test_returns_context(self, git_repo: str) -> None:
        ctx = get_git_context(git_repo)
        assert ctx is not None
        assert "Branch:" in ctx
        assert "Recent commits:" in ctx

    def test_returns_none_for_non_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = get_git_context(tmp)
            assert ctx is None


class TestWorktreeManager:
    def test_list_worktrees(self, git_repo: str) -> None:
        mgr = WorktreeManager(Path(git_repo))
        worktrees = mgr.list()
        assert len(worktrees) >= 1

    def test_create_and_remove(self, git_repo: str) -> None:
        mgr = WorktreeManager(Path(git_repo))
        info = mgr.create(name="test-wt")
        assert info is not None
        assert info.branch == "worktree-test-wt"
        assert Path(info.path).exists()

        # List should include the new worktree
        worktrees = mgr.list()
        branches = [wt.branch for wt in worktrees]
        assert "worktree-test-wt" in branches

        # Remove
        ok = mgr.remove("test-wt")
        assert ok is True


class TestWorktreeInfo:
    def test_repr(self) -> None:
        info = WorktreeInfo(path="/tmp/wt", branch="feature", commit="abc123")
        assert "feature" in repr(info)

    def test_main_repr(self) -> None:
        info = WorktreeInfo(path="/tmp/wt", branch="main", commit="abc", is_main=True)
        assert "(main)" in repr(info)
