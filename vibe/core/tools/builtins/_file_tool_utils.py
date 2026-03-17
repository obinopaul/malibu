from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, auto
import mimetypes
from pathlib import Path

from vibe.core.tools.base import ToolError

SUPPORTED_IMAGE_SUFFIXES = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
_TEXT_WHITESPACE_BYTES = {8, 9, 10, 12, 13}
_ASCII_CONTROL_THRESHOLD = 32
_BINARY_CONTROL_RATIO = 0.05


class FileKind(StrEnum):
    TEXT = auto()
    PDF = auto()
    IMAGE = auto()
    BINARY = auto()


@dataclass(slots=True, frozen=True)
class FileDetection:
    file_kind: FileKind
    mime_type: str


@dataclass(slots=True, frozen=True)
class LineSlice:
    content: str
    lines_read: int
    was_truncated: bool


def resolve_tool_path(path_str: str) -> Path:
    if not path_str.strip():
        raise ToolError("Path cannot be empty")

    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path

    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ToolError(f"Invalid path: {path_str}") from exc


def ensure_existing_file(path: Path) -> Path:
    if not path.exists():
        raise ToolError(f"File not found at: {path}")
    if path.is_dir():
        raise ToolError(f"Path is a directory, not a file: {path}")
    return path


def ensure_existing_directory(path: Path) -> Path:
    if not path.exists():
        raise ToolError(f"Directory not found at: {path}")
    if not path.is_dir():
        raise ToolError(f"Path is not a directory: {path}")
    return path


def ensure_parent_directory(path: Path, *, create: bool) -> None:
    parent = path.parent
    if parent.exists():
        if not parent.is_dir():
            raise ToolError(f"Parent path is not a directory: {parent}")
        return

    if not create:
        raise ToolError(f"Parent directory does not exist: {parent}")

    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ToolError(f"Failed to create parent directory {parent}: {exc}") from exc


def guess_mime_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed

    match path.suffix.lower():
        case ".pdf":
            return "application/pdf"
        case suffix if suffix in SUPPORTED_IMAGE_SUFFIXES:
            if suffix == ".jpg":
                return "image/jpeg"
            return f"image/{suffix.removeprefix('.')}"
        case _:
            return "text/plain"


def detect_file(path: Path) -> FileDetection:
    mime_type = guess_mime_type(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf" or mime_type == "application/pdf":
        return FileDetection(file_kind=FileKind.PDF, mime_type="application/pdf")

    if suffix in SUPPORTED_IMAGE_SUFFIXES or mime_type.startswith("image/"):
        return FileDetection(file_kind=FileKind.IMAGE, mime_type=mime_type)

    try:
        with path.open("rb") as handle:
            sample = handle.read(4096)
    except OSError as exc:
        raise ToolError(f"Error reading {path}: {exc}") from exc

    if _looks_binary(sample):
        return FileDetection(
            file_kind=FileKind.BINARY, mime_type=mime_type or "application/octet-stream"
        )

    return FileDetection(file_kind=FileKind.TEXT, mime_type=mime_type)


def _looks_binary(sample: bytes) -> bool:
    if not sample:
        return False
    if b"\x00" in sample:
        return True

    control_bytes = sum(
        byte < _ASCII_CONTROL_THRESHOLD and byte not in _TEXT_WHITESPACE_BYTES
        for byte in sample
    )
    return (control_bytes / len(sample)) > _BINARY_CONTROL_RATIO


def slice_content_lines(
    lines: list[str], *, offset: int, limit: int | None, max_bytes: int
) -> LineSlice:
    selected = lines[offset:]
    if limit is not None:
        selected = selected[:limit]

    collected: list[str] = []
    bytes_read = 0
    was_truncated = False

    for line in selected:
        line_bytes = len(line.encode("utf-8"))
        if bytes_read + line_bytes > max_bytes:
            was_truncated = True
            break
        collected.append(line)
        bytes_read += line_bytes

    if limit is None and (offset + len(collected)) < len(lines):
        was_truncated = was_truncated or bytes_read >= max_bytes

    return LineSlice(
        content="".join(collected),
        lines_read=len(collected),
        was_truncated=was_truncated,
    )
