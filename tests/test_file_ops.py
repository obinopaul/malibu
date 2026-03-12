"""Tests for malibu.client.file_ops module."""

from __future__ import annotations

import pytest

from malibu.client.file_ops import FileOperations
from malibu.config import Settings


@pytest.fixture
def file_ops(tmp_path, settings) -> FileOperations:
    settings.allowed_paths = [str(tmp_path)]
    return FileOperations(settings, cwd=str(tmp_path))


@pytest.mark.asyncio
async def test_write_and_read(file_ops, tmp_path):
    target = str(tmp_path / "test.txt")
    await file_ops.write_text_file(target, "hello world")
    result = await file_ops.read_text_file(target)
    assert result.content == "hello world"


@pytest.mark.asyncio
async def test_read_with_line_range(file_ops, tmp_path):
    target = str(tmp_path / "lines.txt")
    content = "\n".join(f"line {i}" for i in range(1, 11))
    await file_ops.write_text_file(target, content)
    result = await file_ops.read_text_file(target, line=3, limit=2)
    assert "line 3" in result.content
    assert "line 4" in result.content
    assert "line 5" not in result.content


@pytest.mark.asyncio
async def test_read_nonexistent_raises(file_ops, tmp_path):
    with pytest.raises(FileNotFoundError):
        await file_ops.read_text_file(str(tmp_path / "nope.txt"))


@pytest.mark.asyncio
async def test_path_outside_allowed_raises(file_ops, tmp_path):
    import tempfile
    import os

    other_dir = tempfile.mkdtemp()
    target = os.path.join(other_dir, "evil.txt")
    with pytest.raises(PermissionError, match="outside allowed"):
        await file_ops.write_text_file(target, "bad")


@pytest.mark.asyncio
async def test_write_creates_parent_dirs(file_ops, tmp_path):
    target = str(tmp_path / "a" / "b" / "c" / "deep.txt")
    await file_ops.write_text_file(target, "deep content")
    result = await file_ops.read_text_file(target)
    assert result.content == "deep content"


@pytest.mark.asyncio
async def test_max_file_size_enforced(file_ops, settings):
    settings.max_file_size = 10
    small_ops = FileOperations(settings, cwd=".")
    # Can't actually write due to path restrictions, but we can test the size check
    with pytest.raises(ValueError, match="max file size"):
        await small_ops.write_text_file("/tmp/test.txt", "x" * 100)
