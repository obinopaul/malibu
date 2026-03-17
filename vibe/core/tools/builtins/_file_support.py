from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, auto
import mimetypes
from pathlib import Path

import pymupdf
from PIL import Image, UnidentifiedImageError

from vibe.core.tools.base import ToolError

_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".rst",
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".json",
    ".jsonl",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".log",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".bat",
    ".cmd",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".hxx",
    ".java",
    ".kt",
    ".scala",
    ".go",
    ".rs",
    ".php",
    ".rb",
    ".pl",
    ".lua",
    ".r",
    ".m",
    ".swift",
    ".dart",
    ".tex",
    ".csv",
    ".tsv",
    ".svg",
}

_BINARY_EXTENSIONS = {
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".lz4",
    ".zst",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".a",
    ".lib",
    ".o",
    ".obj",
    ".class",
    ".jar",
    ".war",
    ".ear",
    ".mp4",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".mkv",
    ".webm",
    ".m4v",
    ".mp3",
    ".wav",
    ".flac",
    ".aac",
    ".ogg",
    ".wma",
    ".m4a",
    ".doc",
    ".xls",
    ".ppt",
    ".docx",
    ".xlsx",
    ".pptx",
    ".bin",
    ".dat",
    ".wasm",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".db",
    ".dbf",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    ".stl",
    ".obj",
    ".fbx",
    ".blend",
    ".dwg",
    ".dxf",
}


class FileKind(StrEnum):
    TEXT = auto()
    PDF = auto()
    IMAGE = auto()
    BINARY = auto()


@dataclass(slots=True, frozen=True)
class FileInfo:
    kind: FileKind
    mime_type: str


def resolve_path(path_str: str) -> Path:
    if not path_str.strip():
        raise ToolError("Path cannot be empty")

    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def resolve_existing_file(path_str: str) -> Path:
    path = resolve_path(path_str)
    if not path.exists():
        raise ToolError(f"File not found at: {path}")
    if not path.is_file():
        raise ToolError(f"Path is not a file: {path}")
    return path


def ensure_not_directory(path: Path) -> None:
    if path.exists() and path.is_dir():
        raise ToolError(f"Path is a directory, not a file: {path}")


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


def detect_file_info(path: Path) -> FileInfo:
    suffix = path.suffix.lower()
    mime_type, _ = mimetypes.guess_type(str(path))
    normalized_mime = mime_type or "application/octet-stream"

    if suffix == ".pdf" or normalized_mime == "application/pdf":
        return FileInfo(kind=FileKind.PDF, mime_type="application/pdf")

    if suffix == ".svg" or normalized_mime == "image/svg+xml":
        return FileInfo(kind=FileKind.TEXT, mime_type="image/svg+xml")

    if _looks_like_image(path, normalized_mime):
        return FileInfo(kind=FileKind.IMAGE, mime_type=normalized_mime)

    if suffix in _TEXT_EXTENSIONS or normalized_mime.startswith("text/"):
        return FileInfo(kind=FileKind.TEXT, mime_type=normalized_mime)

    if suffix in _BINARY_EXTENSIONS:
        return FileInfo(kind=FileKind.BINARY, mime_type=normalized_mime)

    if normalized_mime.startswith(("audio/", "video/")):
        return FileInfo(kind=FileKind.BINARY, mime_type=normalized_mime)

    if normalized_mime.startswith("application/"):
        if normalized_mime in {
            "application/json",
            "application/xml",
            "application/javascript",
            "application/x-yaml",
            "application/toml",
        }:
            return FileInfo(kind=FileKind.TEXT, mime_type=normalized_mime)
        return FileInfo(kind=FileKind.BINARY, mime_type=normalized_mime)

    if _is_probably_binary(path):
        return FileInfo(kind=FileKind.BINARY, mime_type=normalized_mime)

    return FileInfo(kind=FileKind.TEXT, mime_type=normalized_mime)


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise ToolError(f"Error reading {path}: {exc}") from exc


def read_pdf_text(path: Path) -> str:
    try:
        with pymupdf.open(path) as document:
            text = "".join(page.get_text("text") for page in document)
    except Exception as exc:
        raise ToolError(f"Error reading PDF {path}: {exc}") from exc

    return text or "[PDF file is empty or no readable text could be extracted]"


def read_image_summary(path: Path) -> tuple[str, str]:
    try:
        with Image.open(path) as image:
            frame_count = getattr(image, "n_frames", 1)
            mime_type = Image.MIME.get(image.format or "", None) or (
                mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            )
            summary_lines = [
                f"Image: {path.name}",
                f"Format: {image.format or 'unknown'}",
                f"MIME Type: {mime_type}",
                f"Size: {image.width}x{image.height}",
                f"Mode: {image.mode}",
                f"Frames: {frame_count}",
            ]

            if image.info:
                info_keys = ", ".join(sorted(str(key) for key in image.info)[:10])
                summary_lines.append(f"Metadata keys: {info_keys or 'none'}")
            else:
                summary_lines.append("Metadata keys: none")
    except (OSError, UnidentifiedImageError) as exc:
        raise ToolError(f"Error reading image {path}: {exc}") from exc

    return "\n".join(summary_lines) + "\n", mime_type


def _looks_like_image(path: Path, mime_type: str) -> bool:
    if mime_type.startswith("image/"):
        return True

    try:
        with Image.open(path):
            return True
    except (OSError, UnidentifiedImageError):
        return False


def _is_probably_binary(path: Path) -> bool:
    try:
        sample = path.read_bytes()[:4096]
    except OSError:
        return False

    if not sample:
        return False

    if b"\x00" in sample:
        return True

    non_printable = sum(
        1 for byte in sample if byte < 9 or 13 < byte < 32
    )
    return non_printable / len(sample) > 0.3
