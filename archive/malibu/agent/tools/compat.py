from __future__ import annotations

import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from malibu.agent.tool_server.core.workspace import FileSystemValidationError
from malibu.agent.tool_server.tools.base import FileURLContent
from malibu.agent.tool_server.tools.file_system.file_edit_tool import (
    FileEditToolError,
    _perform_replacement,
)
from malibu.agent.tool_server.tools.file_system.file_read_tool import (
    _detect_file_type,
    _read_image_file,
    _read_pdf_file,
)
from malibu.agent.tool_server.tools.file_system.grep_tool import (
    GrepToolError,
    _run_ripgrep,
)

from .runtime import ToolRuntime


def _slice_lines(content: str, line: int | None, limit: int | None) -> str:
    if line is not None and line < 1:
        raise ValueError("line must be a positive integer")
    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")

    lines = content.splitlines()
    if not lines:
        return ""

    start = (line - 1) if line else 0
    if start >= len(lines):
        return ""

    end = start + limit if limit else None
    return "\n".join(lines[start:end])


def _run_command(command: str, cwd: Path, timeout: int) -> str:
    if platform.system() == "Windows":
        shell_cmd = ["pwsh", "-NoLogo", "-NoProfile", "-Command", command]
    else:
        shell_cmd = ["/bin/bash", "-lc", command]

    try:
        result = subprocess.run(
            shell_cmd,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout} seconds"
    except OSError as exc:
        return f"Error: failed to execute command: {exc}"

    output_parts = []
    if result.stdout and result.stdout.strip():
        output_parts.append(result.stdout.strip())
    if result.stderr and result.stderr.strip():
        output_parts.append(result.stderr.strip())
    output_parts.append(f"exit code: {result.returncode}")
    return "\n".join(output_parts)


def build_write_todos_tool(runtime: ToolRuntime):
    def write_todos(todos: list[dict[str, str]]) -> str:
        """Create or update the execution plan."""

        runtime.todo_state = list(todos)
        lines = []
        for index, item in enumerate(todos, start=1):
            status = item.get("status", "pending")
            content = item.get("content", "")
            icon = {"completed": "x", "in_progress": ">", "pending": "o"}.get(
                status,
                "o",
            )
            lines.append(f"  {icon} {index}. {content} [{status}]")
        return "Plan updated:\n" + "\n".join(lines)

    return StructuredTool.from_function(
        func=write_todos,
        name="write_todos",
        description="Create or update the execution plan shown to the user.",
    )


def build_read_file_tool(runtime: ToolRuntime):
    def read_file(
        file_path: str,
        line: int | None = None,
        limit: int | None = None,
    ) -> tuple[str, dict[str, Any] | None]:
        """Read a text, PDF, or image file from the workspace."""

        try:
            runtime.workspace_manager.validate_existing_file_path(file_path)
            path = Path(file_path).resolve()
            file_type = _detect_file_type(path)

            if file_type == "binary":
                return (
                    f"Error: Cannot display content of binary file: {file_path}",
                    None,
                )

            if file_type == "image":
                image_content = _read_image_file(path)
                artifact = {
                    "images": [item.model_dump() for item in image_content],
                    "display_content": FileURLContent(
                        type="file_url",
                        url=str(path),
                        mime_type=image_content[0].mime_type,
                        name=path.name,
                        size=path.stat().st_size,
                    ).model_dump(),
                }
                return (f"Image file: {path}", artifact)

            if file_type == "pdf":
                content = _read_pdf_file(path)
            else:
                content = path.read_text(encoding="utf-8")
            return (_slice_lines(content, line, limit), None)
        except (FileSystemValidationError, OSError, ValueError) as exc:
            return (f"Error: {exc}", None)

    return StructuredTool.from_function(
        func=read_file,
        name="read_file",
        description="Read a text, PDF, or image file from the local filesystem.",
        response_format="content_and_artifact",
    )


def build_write_file_tool(runtime: ToolRuntime):
    def write_file(file_path: str, content: str) -> str:
        """Write content to a file, creating parent directories when needed."""

        try:
            runtime.workspace_manager.validate_path(file_path)
            path = Path(file_path).resolve()
            if path.exists() and path.is_dir():
                return f"Error: Path is a directory: {file_path}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"Successfully wrote file: {file_path}"
        except (FileSystemValidationError, OSError) as exc:
            return f"Error: {exc}"

    return StructuredTool.from_function(
        func=write_file,
        name="write_file",
        description="Write text content to a file within the workspace.",
    )


def build_edit_file_tool(runtime: ToolRuntime):
    def edit_file(
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> str:
        """Make an exact string replacement in a file."""

        if old_string == new_string:
            return "Error: old_string and new_string cannot be the same"

        try:
            runtime.workspace_manager.validate_existing_file_path(file_path)
            path = Path(file_path).resolve()
            current_content = path.read_text(encoding="utf-8")
            new_content, occurrences = _perform_replacement(
                current_content,
                old_string,
                new_string,
                replace_all,
            )
            path.write_text(new_content, encoding="utf-8")
            return (
                f"Successfully edited file: {file_path} "
                f"({occurrences} replacement{'s' if occurrences != 1 else ''})"
            )
        except FileEditToolError as exc:
            message = str(exc)
            if "Found " in message and "occurrences" in message:
                count = re.search(r"Found (\d+) occurrences", message)
                if count:
                    return f"Error: old_string appears {count.group(1)} times in the file"
            if "not found" in message:
                return "Error: old_string not found in file"
            return f"Error: {message}"
        except (FileSystemValidationError, OSError) as exc:
            message = str(exc)
            if "does not exist" in message:
                return f"Error: file does not exist: {file_path}"
            return f"Error: {exc}"

    return StructuredTool.from_function(
        func=edit_file,
        name="edit_file",
        description="Replace an exact string inside an existing file.",
    )


def build_ls_tool(runtime: ToolRuntime):
    def ls(path: str | None = None, glob_pattern: str | None = None) -> str:
        """List files and directories inside a workspace path."""

        target = Path(path or runtime.workspace_root).resolve()
        try:
            runtime.workspace_manager.validate_existing_directory_path(str(target))
            entries = (
                list(target.glob(glob_pattern))
                if glob_pattern
                else list(target.iterdir())
            )
            entries = sorted(
                entries,
                key=lambda item: (not item.is_dir(), item.name.lower()),
            )
            if not entries:
                return f"{target} is an empty directory"
            return "\n".join(
                f"{entry.name}/" if entry.is_dir() else entry.name for entry in entries
            )
        except (FileSystemValidationError, OSError) as exc:
            return f"Error: {exc}"

    return StructuredTool.from_function(
        func=ls,
        name="ls",
        description="List files and directories inside a workspace path.",
    )


def build_grep_tool(runtime: ToolRuntime):
    def grep(
        pattern: str,
        path: str | None = None,
        glob_pattern: str | None = None,
        max_results: int = 50,
    ) -> str:
        """Search file contents using a regular expression."""

        try:
            re.compile(pattern)
            target = Path(path or runtime.workspace_root).resolve()
            runtime.workspace_manager.validate_existing_directory_path(str(target))

            if shutil.which("rg"):
                matches = _run_ripgrep(pattern, target, glob_pattern)
            else:
                matches = []
                for candidate in target.rglob(glob_pattern or "*"):
                    if not candidate.is_file():
                        continue
                    try:
                        for index, content in enumerate(
                            candidate.read_text(encoding="utf-8").splitlines(),
                            start=1,
                        ):
                            if re.search(pattern, content):
                                matches.append(
                                    {
                                        "file_path": str(candidate),
                                        "line_number": str(index),
                                        "content": content,
                                    }
                                )
                    except (OSError, UnicodeDecodeError):
                        continue

            if not matches:
                return f"No matches found for pattern '{pattern}'"

            lines = [
                f"{match['file_path']}:{match['line_number']}:{match['content']}"
                for match in matches[:max_results]
            ]
            return "\n".join(lines)
        except re.error as exc:
            return f"Error: invalid regular expression: {exc}"
        except (FileSystemValidationError, GrepToolError, OSError) as exc:
            return f"Error: {exc}"

    return StructuredTool.from_function(
        func=grep,
        name="grep",
        description="Search file contents using ripgrep-style regex matching.",
    )


def build_execute_tool(runtime: ToolRuntime):
    def execute(
        command: str,
        cwd: str | None = None,
        timeout: int = 60,
    ) -> str:
        """Run a one-shot shell command."""

        target = Path(cwd or runtime.workspace_root).resolve()
        try:
            runtime.workspace_manager.validate_existing_directory_path(str(target))
        except (FileSystemValidationError, OSError) as exc:
            return f"Error: {exc}"
        return _run_command(command, target, timeout)

    return StructuredTool.from_function(
        func=execute,
        name="execute",
        description="Run a one-shot shell command in the workspace.",
    )


def build_git_tools(runtime: ToolRuntime):
    def git_status(cwd: str | None = None) -> str:
        """Show git status for a repository."""

        from malibu.git.operations import GitOperations

        return GitOperations(cwd or str(runtime.workspace_root)).status()

    def git_diff(staged: bool = False, cwd: str | None = None) -> str:
        """Show git diff for a repository."""

        from malibu.git.operations import GitOperations

        return GitOperations(cwd or str(runtime.workspace_root)).diff(staged=staged)

    def git_log(n: int = 10, cwd: str | None = None) -> str:
        """Show recent git commits."""

        from malibu.git.operations import GitOperations

        return GitOperations(cwd or str(runtime.workspace_root)).log(n=n)

    def git_commit(
        message: str,
        files: list[str] | None = None,
        cwd: str | None = None,
    ) -> str:
        """Create a git commit in the target repository."""

        from malibu.git.operations import GitOperations

        return GitOperations(cwd or str(runtime.workspace_root)).commit(
            message,
            files=files,
        )

    def git_worktree_create(
        name: str | None = None,
        branch: str | None = None,
        cwd: str | None = None,
    ) -> str:
        """Create a new git worktree."""

        from malibu.git.worktree import WorktreeManager

        manager = WorktreeManager(Path(cwd or runtime.workspace_root))
        info = manager.create(name=name, branch=branch)
        if info is None:
            return "Error: failed to create worktree"
        return f"Created worktree '{info.branch}' at {info.path}"

    def git_worktree_list(cwd: str | None = None) -> str:
        """List git worktrees."""

        from malibu.git.worktree import WorktreeManager

        manager = WorktreeManager(Path(cwd or runtime.workspace_root))
        worktrees = manager.list()
        if not worktrees:
            return "(no worktrees)"
        return "\n".join(
            f"{worktree.branch} -> {worktree.path}" for worktree in worktrees
        )

    def git_worktree_remove(
        name: str,
        force: bool = False,
        cwd: str | None = None,
    ) -> str:
        """Remove a git worktree."""

        from malibu.git.worktree import WorktreeManager

        manager = WorktreeManager(Path(cwd or runtime.workspace_root))
        ok = manager.remove(name, force=force)
        if ok:
            return f"Worktree '{name}' removed"
        return f"Error: failed to remove worktree '{name}'"

    return [
        StructuredTool.from_function(
            func=git_status,
            name="git_status",
            description="Show git status of the working directory.",
        ),
        StructuredTool.from_function(
            func=git_diff,
            name="git_diff",
            description="Show git diff for the working directory.",
        ),
        StructuredTool.from_function(
            func=git_log,
            name="git_log",
            description="Show recent git commit history.",
        ),
        StructuredTool.from_function(
            func=git_commit,
            name="git_commit",
            description="Create a git commit in the current repository.",
        ),
        StructuredTool.from_function(
            func=git_worktree_create,
            name="git_worktree_create",
            description="Create a git worktree for isolated work.",
        ),
        StructuredTool.from_function(
            func=git_worktree_list,
            name="git_worktree_list",
            description="List git worktrees for the repository.",
        ),
        StructuredTool.from_function(
            func=git_worktree_remove,
            name="git_worktree_remove",
            description="Remove a git worktree.",
        ),
    ]


def build_core_tool_map(runtime: ToolRuntime) -> dict[str, Any]:
    return {
        "write_todos": build_write_todos_tool(runtime),
        "read_file": build_read_file_tool(runtime),
        "write_file": build_write_file_tool(runtime),
        "edit_file": build_edit_file_tool(runtime),
        "ls": build_ls_tool(runtime),
        "grep": build_grep_tool(runtime),
        "execute": build_execute_tool(runtime),
    }
