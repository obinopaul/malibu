"""File I/O operations for the ACP client.

Implements the client-side handlers for fs/read_text_file and
fs/write_text_file with path validation and security checks.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from acp.schema import ReadTextFileResponse, WriteTextFileResponse

from malibu.config import Settings
from malibu.telemetry.logging import get_logger

log = get_logger(__name__)


class FileOperations:
    """Secure file read/write handler with path allowlisting."""

    def __init__(self, settings: Settings, *, cwd: str) -> None:
        self._max_file_size = settings.max_file_size
        self._allowed_roots = settings.resolve_allowed_paths(cwd)

    def _validate_path(self, path: str) -> Path:
        """Resolve and validate a path is within allowed roots."""
        resolved = Path(path).resolve()
        if not any(self._is_subpath(resolved, root) for root in self._allowed_roots):
            raise PermissionError(f"Path {path} is outside allowed directories")
        return resolved

    @staticmethod
    def _is_subpath(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    async def read_text_file(
        self, path: str, *, line: int | None = None, limit: int | None = None
    ) -> ReadTextFileResponse:
        """Read a text file and return its contents."""
        resolved = self._validate_path(path)
        if not resolved.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        text = await asyncio.to_thread(resolved.read_text, encoding="utf-8", errors="replace")

        if line is not None or limit is not None:
            lines = text.splitlines(keepends=True)
            start = (line - 1) if line and line > 0 else 0
            end = (start + limit) if limit else len(lines)
            text = "".join(lines[start:end])

        log.info("read_text_file", path=str(resolved), size=len(text))
        return ReadTextFileResponse(content=text)

    async def write_text_file(self, path: str, content: str) -> WriteTextFileResponse | None:
        """Write content to a text file."""
        if len(content.encode("utf-8")) > self._max_file_size:
            raise ValueError(f"Content exceeds max file size of {self._max_file_size} bytes")

        resolved = self._validate_path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(resolved.write_text, content, encoding="utf-8")
        log.info("write_text_file", path=str(resolved), size=len(content))
        return WriteTextFileResponse()
