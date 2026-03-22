from __future__ import annotations

from pathlib import Path

import pytest

from tests.mock.utils import collect_result
from vibe.core.tools.base import BaseToolState, ToolError
from vibe.core.tools.builtins._file_tool_utils import FileKind
from vibe.core.tools.builtins.read_file import (
    ReadFile,
    ReadFileArgs,
    ReadFileToolConfig,
)


@pytest.fixture
def read_file_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ReadFile:
    monkeypatch.chdir(tmp_path)
    return ReadFile(config=ReadFileToolConfig(), state=BaseToolState())


@pytest.mark.asyncio
async def test_read_text_file_preserves_line_offset_and_limit(
    read_file_tool: ReadFile, tmp_path: Path
) -> None:
    path = tmp_path / "example.py"
    path.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = await collect_result(
        read_file_tool.run(ReadFileArgs(path=str(path), offset=1, limit=2))
    )

    assert result.content == "two\nthree\n"
    assert result.lines_read == 2
    assert result.file_kind is FileKind.TEXT
    assert result.mime_type == "text/x-python"
    assert result.was_truncated is False


@pytest.mark.asyncio
async def test_read_pdf_extracts_text_before_line_window(
    read_file_tool: ReadFile, tmp_path: Path
) -> None:
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "sample.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "alpha\nbeta\ngamma\ndelta")
    document.save(path)
    document.close()

    result = await collect_result(
        read_file_tool.run(ReadFileArgs(path=str(path), offset=1, limit=2))
    )

    assert result.content == "beta\ngamma\n"
    assert result.lines_read == 2
    assert result.file_kind is FileKind.PDF
    assert result.mime_type == "application/pdf"


@pytest.mark.asyncio
async def test_read_supported_image_returns_metadata_summary(
    read_file_tool: ReadFile, tmp_path: Path
) -> None:
    image_module = pytest.importorskip("PIL.Image")
    path = tmp_path / "sample.png"
    image = image_module.new("RGB", (64, 32), color=(255, 0, 0))
    image.save(path)

    result = await collect_result(read_file_tool.run(ReadFileArgs(path=str(path))))

    assert "Dimensions: 64x32" in result.content
    assert "Mode: RGB" in result.content
    assert result.file_kind is FileKind.IMAGE
    assert result.mime_type == "image/png"


@pytest.mark.asyncio
async def test_read_binary_file_rejected(
    read_file_tool: ReadFile, tmp_path: Path
) -> None:
    path = tmp_path / "archive.bin"
    path.write_bytes(b"\x00\x01\x02\x03")

    with pytest.raises(ToolError, match="Unsupported binary file"):
        await collect_result(read_file_tool.run(ReadFileArgs(path=str(path))))
