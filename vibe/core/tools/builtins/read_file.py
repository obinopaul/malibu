from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final

import anyio
from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.builtins._file_tool_utils import (
    FileKind,
    detect_file,
    ensure_existing_file,
    resolve_tool_path,
    slice_content_lines,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.tools.utils import resolve_file_tool_permission
from vibe.core.types import ToolStreamEvent

if TYPE_CHECKING:
    from vibe.core.types import ToolResultEvent


class _ReadResult(NamedTuple):
    lines: list[str]
    bytes_read: int
    was_truncated: bool
    file_kind: FileKind
    mime_type: str


class ReadFileArgs(BaseModel):
    path: str
    offset: int = Field(
        default=0,
        description="Line number to start reading from (0-indexed, inclusive).",
    )
    limit: int | None = Field(
        default=None, description="Maximum number of lines to read."
    )


class ReadFileResult(BaseModel):
    path: str
    content: str
    lines_read: int
    file_kind: FileKind
    mime_type: str
    was_truncated: bool = Field(
        description="True if the reading was stopped due to the max_read_bytes limit."
    )


class ReadFileToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS

    max_read_bytes: int = Field(
        default=64_000, description="Maximum total bytes to read from a file in one go."
    )


class ReadFile(
    BaseTool[ReadFileArgs, ReadFileResult, ReadFileToolConfig, BaseToolState],
    ToolUIData[ReadFileArgs, ReadFileResult],
):
    description: ClassVar[str] = (
        "Read local files with line-based paging. "
        "Text files are returned directly, PDFs are extracted to text, "
        "and supported images return metadata summaries."
    )

    @final
    async def run(
        self, args: ReadFileArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ReadFileResult, None]:
        file_path = self._prepare_and_validate_path(args)

        read_result = await self._read_file(args, file_path)

        yield ReadFileResult(
            path=str(file_path),
            content="".join(read_result.lines),
            lines_read=len(read_result.lines),
            file_kind=read_result.file_kind,
            mime_type=read_result.mime_type,
            was_truncated=read_result.was_truncated,
        )

    def resolve_permission(self, args: ReadFileArgs) -> ToolPermission | None:
        return resolve_file_tool_permission(
            args.path,
            allowlist=self.config.allowlist,
            denylist=self.config.denylist,
            config_permission=self.config.permission,
        )

    def _prepare_and_validate_path(self, args: ReadFileArgs) -> Path:
        self._validate_inputs(args)
        return ensure_existing_file(resolve_tool_path(args.path))

    async def _read_file(self, args: ReadFileArgs, file_path: Path) -> _ReadResult:
        detection = detect_file(file_path)

        match detection.file_kind:
            case FileKind.TEXT:
                return await self._read_text_file(args, file_path, detection.mime_type)
            case FileKind.PDF:
                return await anyio.to_thread.run_sync(
                    self._read_pdf_file, args, file_path, detection.mime_type
                )
            case FileKind.IMAGE:
                return await anyio.to_thread.run_sync(
                    self._read_image_file, args, file_path, detection.mime_type
                )
            case FileKind.BINARY:
                raise ToolError(
                    f"Unsupported binary file: {file_path} ({detection.mime_type})"
                )

    async def _read_text_file(
        self, args: ReadFileArgs, file_path: Path, mime_type: str
    ) -> _ReadResult:
        try:
            lines_to_return: list[str] = []
            bytes_read = 0
            was_truncated = False

            async with await anyio.Path(file_path).open(
                encoding="utf-8", errors="replace"
            ) as f:
                line_index = 0
                async for line in f:
                    if line_index < args.offset:
                        line_index += 1
                        continue

                    if args.limit is not None and len(lines_to_return) >= args.limit:
                        break

                    line_bytes = len(line.encode("utf-8"))
                    if bytes_read + line_bytes > self.config.max_read_bytes:
                        was_truncated = True
                        break

                    lines_to_return.append(line)
                    bytes_read += line_bytes
                    line_index += 1

            return _ReadResult(
                lines=lines_to_return,
                bytes_read=bytes_read,
                was_truncated=was_truncated,
                file_kind=FileKind.TEXT,
                mime_type=mime_type,
            )

        except OSError as exc:
            raise ToolError(f"Error reading {file_path}: {exc}") from exc

    def _read_pdf_file(
        self, args: ReadFileArgs, file_path: Path, mime_type: str
    ) -> _ReadResult:
        try:
            import fitz
        except ImportError as exc:
            raise ToolError(
                "PDF support requires the optional 'pymupdf' dependency."
            ) from exc

        try:
            with fitz.open(file_path) as document:
                extracted = "\n".join(page.get_text("text") for page in document)
        except Exception as exc:
            raise ToolError(
                f"Error extracting PDF text from {file_path}: {exc}"
            ) from exc

        lines = extracted.splitlines(keepends=True)
        sliced = slice_content_lines(
            lines,
            offset=args.offset,
            limit=args.limit,
            max_bytes=self.config.max_read_bytes,
        )
        return _ReadResult(
            lines=sliced.content.splitlines(keepends=True),
            bytes_read=len(sliced.content.encode("utf-8")),
            was_truncated=sliced.was_truncated,
            file_kind=FileKind.PDF,
            mime_type=mime_type,
        )

    def _read_image_file(
        self, args: ReadFileArgs, file_path: Path, mime_type: str
    ) -> _ReadResult:
        try:
            from PIL import Image
        except ImportError as exc:
            raise ToolError(
                "Image metadata support requires the optional 'pillow' dependency."
            ) from exc

        try:
            with Image.open(file_path) as image:
                summary_lines = [
                    f"Path: {file_path}\n",
                    f"Format: {image.format or file_path.suffix.removeprefix('.').upper()}\n",
                    f"MIME Type: {mime_type}\n",
                    f"Dimensions: {image.width}x{image.height}\n",
                    f"Mode: {image.mode}\n",
                    f"Animated: {bool(getattr(image, 'is_animated', False))}\n",
                    f"Frames: {getattr(image, 'n_frames', 1)}\n",
                ]
        except Exception as exc:
            raise ToolError(
                f"Error reading image metadata from {file_path}: {exc}"
            ) from exc

        sliced = slice_content_lines(
            summary_lines,
            offset=args.offset,
            limit=args.limit,
            max_bytes=self.config.max_read_bytes,
        )
        return _ReadResult(
            lines=sliced.content.splitlines(keepends=True),
            bytes_read=len(sliced.content.encode("utf-8")),
            was_truncated=sliced.was_truncated,
            file_kind=FileKind.IMAGE,
            mime_type=mime_type,
        )

    def _validate_inputs(self, args: ReadFileArgs) -> None:
        if args.offset < 0:
            raise ToolError("Offset cannot be negative")
        if args.limit is not None and args.limit <= 0:
            raise ToolError("Limit, if provided, must be a positive number")

    @classmethod
    def format_call_display(cls, args: ReadFileArgs) -> ToolCallDisplay:
        summary = f"Reading {args.path}"
        if args.offset > 0 or args.limit is not None:
            parts = []
            if args.offset > 0:
                parts.append(f"from line {args.offset}")
            if args.limit is not None:
                parts.append(f"limit {args.limit} lines")
            summary += f" ({', '.join(parts)})"
        return ToolCallDisplay(summary=summary)

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ReadFileResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        path_obj = Path(event.result.path)
        match event.result.file_kind:
            case FileKind.IMAGE:
                message = f"Read image metadata from {path_obj.name}"
            case FileKind.PDF:
                message = (
                    f"Read {event.result.lines_read} extracted line"
                    f"{'' if event.result.lines_read == 1 else 's'} from {path_obj.name}"
                )
            case _:
                message = (
                    f"Read {event.result.lines_read} line"
                    f"{'' if event.result.lines_read == 1 else 's'} from {path_obj.name}"
                )
        if event.result.was_truncated:
            message += " (truncated)"

        return ToolResultDisplay(
            success=True,
            message=message,
            warnings=["File was truncated due to size limit"]
            if event.result.was_truncated
            else [],
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Reading file"
