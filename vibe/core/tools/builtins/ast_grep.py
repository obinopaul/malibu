from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import json
from pathlib import Path
import shutil
from typing import Any, ClassVar

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
    ensure_existing_directory,
    resolve_tool_path,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolResultEvent, ToolStreamEvent

SUPPORTED_BINARIES = ("ast-grep", "sg")


class AstGrepArgs(BaseModel):
    pattern: str
    path: str = "."
    include: str | None = None
    language: str | None = None


class AstGrepResult(BaseModel):
    matches: str
    match_count: int
    was_truncated: bool = Field(
        description="True if output was truncated due to result limits."
    )


class AstGrepConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    default_timeout: int = Field(
        default=30, description="Default timeout for ast-grep in seconds."
    )
    max_results: int = Field(
        default=100, description="Maximum number of matches to return."
    )


class AstGrep(
    BaseTool[AstGrepArgs, AstGrepResult, AstGrepConfig, BaseToolState],
    ToolUIData[AstGrepArgs, AstGrepResult],
):
    description: ClassVar[str] = (
        "Search code structurally with ast-grep using language-aware AST patterns."
    )

    @classmethod
    def is_available(cls) -> bool:
        return any(shutil.which(binary) for binary in SUPPORTED_BINARIES)

    async def run(
        self, args: AstGrepArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | AstGrepResult, None]:
        executable = self._find_executable()
        resolved = resolve_tool_path(args.path)

        # If the user passed a file path, search its parent directory
        # and scope results to that file via --globs
        if resolved.is_file():
            search_path = resolved.parent
            # Merge with any existing include filter
            args = args.model_copy(
                update={"include": resolved.name},
            )
        else:
            search_path = ensure_existing_directory(resolved)

        self._validate_args(args)

        command = self._build_command(executable, args, search_path)
        matches = await self._execute(command)
        formatted, match_count, was_truncated = self._format_matches(matches)

        yield AstGrepResult(
            matches=formatted, match_count=match_count, was_truncated=was_truncated
        )

    def _find_executable(self) -> str:
        for binary in SUPPORTED_BINARIES:
            if path := shutil.which(binary):
                return path
        raise ToolError("ast-grep is not installed or not available on PATH.")

    def _validate_args(self, args: AstGrepArgs) -> None:
        if not args.pattern.strip():
            raise ToolError("Pattern cannot be empty")

    def _build_command(
        self, executable: str, args: AstGrepArgs, search_path: Path
    ) -> list[str]:
        command = [executable, "run", "--json=compact", "--pattern", args.pattern]
        if args.language:
            command.extend(["--lang", args.language])
        if args.include:
            command.extend(["--globs", args.include])
        command.append(str(search_path))
        return command

    async def _execute(self, command: list[str]) -> list[dict[str, Any]]:
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=self.config.default_timeout
                )
            except TimeoutError as exc:
                process.kill()
                await process.wait()
                raise ToolError(
                    f"ast-grep timed out after {self.config.default_timeout}s"
                ) from exc
        except OSError as exc:
            raise ToolError(f"Failed to start ast-grep: {exc}") from exc

        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

        if process.returncode == 1:
            return []
        if process.returncode != 0:
            raise ToolError(
                stderr or f"ast-grep failed with exit code {process.returncode}"
            )
        if not stdout:
            return []

        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, list):
                return [match for match in parsed if isinstance(match, dict)]
        except json.JSONDecodeError:
            pass

        matches: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                matches.append(parsed)
        return matches

    def _format_matches(self, matches: list[dict[str, Any]]) -> tuple[str, int, bool]:
        if not matches:
            return "", 0, False

        was_truncated = len(matches) > self.config.max_results
        limited_matches = matches[: self.config.max_results]

        lines: list[str] = []
        for match in limited_matches:
            file_path = str(match.get("file", "unknown"))
            start = match.get("range", {}).get("start", {})
            line_number = start.get("line")
            human_line = (line_number + 1) if isinstance(line_number, int) else "?"
            text = str(match.get("text", "")).strip()
            lines.append(f"{file_path}:{human_line}: {text}")

        return "\n".join(lines), len(limited_matches), was_truncated

    @classmethod
    def format_call_display(cls, args: AstGrepArgs) -> ToolCallDisplay:
        summary = f"ast-grep: {args.pattern}"
        if args.path != ".":
            summary += f" in {args.path}"
        return ToolCallDisplay(summary=summary)

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, AstGrepResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        warnings = (
            [f"Results truncated to {event.result.match_count} matches"]
            if event.result.was_truncated
            else []
        )
        return ToolResultDisplay(
            success=True,
            message=f"Found {event.result.match_count} structural matches",
            warnings=warnings,
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Running ast-grep"
