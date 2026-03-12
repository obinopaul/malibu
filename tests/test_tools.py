"""Tests for malibu.agent.tools — all 7 agent tools."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from malibu.agent.tools import ALL_TOOLS, edit_file, execute, grep, ls, read_file, write_file, write_todos


# ═══════════════════════════════════════════════════════════════════
# read_file
# ═══════════════════════════════════════════════════════════════════

class TestReadFile:
    def test_read_whole_file(self, tmp_path: Path):
        f = tmp_path / "hello.txt"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = read_file.invoke({"file_path": str(f)})
        assert "line1" in result
        assert "line3" in result

    def test_read_with_line_and_limit(self, tmp_path: Path):
        f = tmp_path / "lines.txt"
        f.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
        result = read_file.invoke({"file_path": str(f), "line": 2, "limit": 2})
        assert "b" in result
        assert "c" in result
        assert "a" not in result
        assert "d" not in result

    def test_read_nonexistent(self, tmp_path: Path):
        result = read_file.invoke({"file_path": str(tmp_path / "nope.txt")})
        assert "Error" in result

    def test_read_line_beyond_end(self, tmp_path: Path):
        f = tmp_path / "short.txt"
        f.write_text("only\n", encoding="utf-8")
        result = read_file.invoke({"file_path": str(f), "line": 100})
        assert result == ""


# ═══════════════════════════════════════════════════════════════════
# write_file
# ═══════════════════════════════════════════════════════════════════

class TestWriteFile:
    def test_write_creates_file(self, tmp_path: Path):
        target = tmp_path / "out.txt"
        result = write_file.invoke({"file_path": str(target), "content": "hello world"})
        assert "Successfully wrote" in result
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_write_creates_parent_dirs(self, tmp_path: Path):
        target = tmp_path / "a" / "b" / "c.txt"
        write_file.invoke({"file_path": str(target), "content": "deep"})
        assert target.read_text(encoding="utf-8") == "deep"

    def test_write_overwrites_existing(self, tmp_path: Path):
        target = tmp_path / "existing.txt"
        target.write_text("old", encoding="utf-8")
        write_file.invoke({"file_path": str(target), "content": "new"})
        assert target.read_text(encoding="utf-8") == "new"


# ═══════════════════════════════════════════════════════════════════
# edit_file
# ═══════════════════════════════════════════════════════════════════

class TestEditFile:
    def test_edit_replaces_unique_string(self, tmp_path: Path):
        f = tmp_path / "code.py"
        f.write_text("def foo():\n    return 1\n", encoding="utf-8")
        result = edit_file.invoke({"file_path": str(f), "old_string": "return 1", "new_string": "return 42"})
        assert "Successfully edited" in result
        assert "return 42" in f.read_text(encoding="utf-8")

    def test_edit_not_found(self, tmp_path: Path):
        f = tmp_path / "code.py"
        f.write_text("hello", encoding="utf-8")
        result = edit_file.invoke({"file_path": str(f), "old_string": "missing", "new_string": "x"})
        assert "not found" in result

    def test_edit_multiple_occurrences(self, tmp_path: Path):
        f = tmp_path / "dup.txt"
        f.write_text("aaa bbb aaa", encoding="utf-8")
        result = edit_file.invoke({"file_path": str(f), "old_string": "aaa", "new_string": "ccc"})
        assert "appears 2 times" in result

    def test_edit_nonexistent_file(self, tmp_path: Path):
        result = edit_file.invoke({"file_path": str(tmp_path / "nope.py"), "old_string": "x", "new_string": "y"})
        assert "does not exist" in result


# ═══════════════════════════════════════════════════════════════════
# ls
# ═══════════════════════════════════════════════════════════════════

class TestLs:
    def test_ls_directory(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("", encoding="utf-8")
        (tmp_path / "b.py").write_text("", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        result = ls.invoke({"path": str(tmp_path)})
        assert "a.txt" in result
        assert "b.py" in result
        assert "sub/" in result

    def test_ls_with_glob(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("", encoding="utf-8")
        (tmp_path / "b.py").write_text("", encoding="utf-8")
        result = ls.invoke({"path": str(tmp_path), "glob_pattern": "*.py"})
        assert "b.py" in result
        assert "a.txt" not in result

    def test_ls_nonexistent(self):
        result = ls.invoke({"path": "/nonexistent/path/xyz"})
        assert "Error" in result

    def test_ls_empty_dir(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = ls.invoke({"path": str(empty)})
        assert "empty directory" in result


# ═══════════════════════════════════════════════════════════════════
# grep
# ═══════════════════════════════════════════════════════════════════

class TestGrep:
    def test_grep_finds_pattern(self, tmp_path: Path):
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    print('hi')\n", encoding="utf-8")
        result = grep.invoke({"pattern": "hello", "path": str(tmp_path)})
        assert "hello" in result
        assert "code.py" in result

    def test_grep_no_match(self, tmp_path: Path):
        f = tmp_path / "code.py"
        f.write_text("some code\n", encoding="utf-8")
        result = grep.invoke({"pattern": "nonexistent_xyz", "path": str(tmp_path)})
        assert "No matches" in result

    def test_grep_max_results(self, tmp_path: Path):
        f = tmp_path / "many.txt"
        f.write_text("\n".join(f"match line {i}" for i in range(200)), encoding="utf-8")
        result = grep.invoke({"pattern": "match", "path": str(tmp_path), "max_results": 5})
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) <= 5

    def test_grep_invalid_regex(self, tmp_path: Path):
        result = grep.invoke({"pattern": "[invalid", "path": str(tmp_path)})
        assert "Error" in result

    def test_grep_nonexistent_path(self):
        result = grep.invoke({"pattern": "x", "path": "/nonexistent/abc"})
        assert "Error" in result


# ═══════════════════════════════════════════════════════════════════
# execute
# ═══════════════════════════════════════════════════════════════════

class TestExecute:
    def test_execute_simple_command(self, tmp_path: Path):
        # Use a platform-independent echo
        result = execute.invoke({"command": "echo hello_world", "cwd": str(tmp_path)})
        assert "exit code: 0" in result
        assert "hello_world" in result

    def test_execute_failing_command(self, tmp_path: Path):
        # A command that returns non-zero
        result = execute.invoke({"command": "python -c \"import sys; sys.exit(1)\"", "cwd": str(tmp_path)})
        assert "exit code: 1" in result

    def test_execute_timeout(self, tmp_path: Path):
        result = execute.invoke({
            "command": "python -c \"import time; time.sleep(10)\"",
            "cwd": str(tmp_path),
            "timeout": 1,
        })
        assert "timed out" in result

    def test_execute_does_not_inherit_stdin(self, tmp_path: Path):
        """Child process must not inherit parent stdin (the ACP pipe)."""
        result = execute.invoke({
            "command": 'python -c "import sys; print(sys.stdin.readable())"',
            "cwd": str(tmp_path),
        })
        assert "exit code: 0" in result
        # stdin is /dev/null so readable() should still be True, but
        # reading should return empty — the key check is it doesn't hang.

    def test_execute_python_c_datetime(self, tmp_path: Path):
        """Regression: python -c with semicolons must not hang."""
        result = execute.invoke({
            "command": 'python -c "from datetime import datetime; print(datetime.now())"',
            "cwd": str(tmp_path),
        })
        assert "exit code: 0" in result


# ═══════════════════════════════════════════════════════════════════
# write_todos
# ═══════════════════════════════════════════════════════════════════

class TestWriteTodos:
    def test_write_todos_returns_count(self):
        result = write_todos.invoke({"todos": [
            {"content": "Step 1", "status": "pending"},
            {"content": "Step 2", "status": "pending"},
        ]})
        assert "2 items" in result

    def test_write_todos_empty(self):
        result = write_todos.invoke({"todos": []})
        assert "0 items" in result


# ═══════════════════════════════════════════════════════════════════
# ALL_TOOLS collection
# ═══════════════════════════════════════════════════════════════════

def test_all_tools_contains_expected():
    names = {t.name for t in ALL_TOOLS}
    assert names == {"read_file", "write_file", "edit_file", "ls", "grep", "execute", "write_todos"}
