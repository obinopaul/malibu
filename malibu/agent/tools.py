"""Tool definitions for the Malibu agent.

Each tool uses the ``@tool`` decorator from ``langchain_core.tools``.
The ``create_agent()`` call binds them automatically — no manual ToolNode needed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


# ═══════════════════════════════════════════════════════════════════
# Filesystem tools
# ═══════════════════════════════════════════════════════════════════
@tool
def read_file(file_path: str, line: int | None = None, limit: int | None = None) -> str:
    """Read the contents of a text file.

    Args:
        file_path: Absolute or relative path to the file.
        line: Starting line number (1-based). If omitted, reads from the beginning.
        limit: Maximum number of lines to read. If omitted, reads the entire file.
    """
    p = Path(file_path).resolve()
    if not p.is_file():
        return f"Error: {file_path} does not exist or is not a file"
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    start = (line - 1) if line and line > 0 else 0
    end = (start + limit) if limit else len(lines)
    return "".join(lines[start:end])


@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a text file (creates parent directories if needed).

    Args:
        file_path: Absolute or relative path to the file.
        content: The text content to write.
    """
    p = Path(file_path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Successfully wrote {len(content)} bytes to {file_path}"


@tool
def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """Replace an exact substring in a file.

    Args:
        file_path: Absolute or relative path to the file.
        old_string: The exact text to find and replace. Must appear exactly once.
        new_string: The replacement text.
    """
    p = Path(file_path).resolve()
    if not p.is_file():
        return f"Error: {file_path} does not exist"
    text = p.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        return f"Error: old_string not found in {file_path}"
    if count > 1:
        return f"Error: old_string appears {count} times in {file_path} — must be unique"
    text = text.replace(old_string, new_string, 1)
    p.write_text(text, encoding="utf-8")
    return f"Successfully edited {file_path}"


@tool
def ls(path: str = ".", glob_pattern: str | None = None) -> str:
    """List directory contents or search with a glob pattern.

    Args:
        path: Directory path to list.
        glob_pattern: Optional glob pattern to filter results (e.g. '*.py').
    """
    p = Path(path).resolve()
    if not p.is_dir():
        return f"Error: {path} is not a directory"
    if glob_pattern:
        entries = sorted(p.glob(glob_pattern))
    else:
        entries = sorted(p.iterdir())
    lines = []
    for entry in entries[:500]:  # Cap at 500 entries
        suffix = "/" if entry.is_dir() else ""
        lines.append(f"{entry.name}{suffix}")
    return "\n".join(lines) if lines else "(empty directory)"


@tool
def grep(pattern: str, path: str = ".", include: str | None = None, max_results: int = 100) -> str:
    """Search for a text pattern in files.

    Args:
        pattern: The text or regex pattern to search for.
        path: Root directory to search.
        include: Glob pattern to filter files (e.g. '*.py').
        max_results: Maximum number of matching lines to return.
    """
    root = Path(path).resolve()
    if not root.exists():
        return f"Error: {path} does not exist"

    import re

    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Error: invalid regex — {e}"

    results: list[str] = []
    glob_pat = include or "**/*"
    for fpath in root.glob(glob_pat):
        if not fpath.is_file():
            continue
        try:
            for lineno, line in enumerate(fpath.open(encoding="utf-8", errors="replace"), 1):
                if rx.search(line):
                    rel = fpath.relative_to(root)
                    results.append(f"{rel}:{lineno}: {line.rstrip()}")
                    if len(results) >= max_results:
                        break
        except (OSError, UnicodeDecodeError):
            continue
        if len(results) >= max_results:
            break
    return "\n".join(results) if results else "No matches found"


# ═══════════════════════════════════════════════════════════════════
# Shell execution
# ═══════════════════════════════════════════════════════════════════
@tool
def execute(command: str, cwd: str | None = None, timeout: int = 120) -> str:
    """Execute a shell command and return its combined stdout/stderr.

    Use this for running tests, installing packages, checking git status, etc.
    The user must approve shell commands in most modes.

    Args:
        command: The command to run (passed to the system shell).
        cwd: Working directory. Defaults to the session cwd.
        timeout: Maximum seconds to wait for completion.
    """
    import shlex

    try:
        # Use shell=True because commands often use pipes, redirects, &&, etc.
        # Security: the ACP HITL layer gates every shell invocation.
        # stdin=DEVNULL prevents the child from inheriting the ACP stdio pipe,
        # which would cause hangs when the agent runs as a subprocess.
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            timeout=timeout,
            env={**os.environ},
        )
        output = result.stdout + result.stderr
        if len(output) > 50_000:
            output = output[:25_000] + "\n\n... (truncated) ...\n\n" + output[-25_000:]
        return f"exit code: {result.returncode}\n{output}"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


# ═══════════════════════════════════════════════════════════════════
# Plan / TODO management
# ═══════════════════════════════════════════════════════════════════
@tool
def write_todos(todos: list[dict[str, str]]) -> str:
    """Create or update the execution plan.

    Args:
        todos: List of dicts with 'content' and 'status' keys.
               Status is one of 'pending', 'in_progress', 'completed'.
    """
    return f"Plan updated with {len(todos)} items"


# ═══════════════════════════════════════════════════════════════════
# Collected tool list
# ═══════════════════════════════════════════════════════════════════
ALL_TOOLS = [read_file, write_file, edit_file, ls, grep, execute, write_todos]
