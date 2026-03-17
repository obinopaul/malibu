from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from vibe.core.git import GitOperations
from vibe.core.session.session_loader import SessionLoader

if TYPE_CHECKING:
    from vibe.core.tools.base import InvokeContext


def canonical_workspace_root(path: str | Path | None = None) -> Path:
    fallback = Path.cwd().resolve()
    candidate = Path(path or fallback).expanduser()

    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        resolved = fallback

    if resolved.is_file():
        resolved = resolved.parent

    if not resolved.exists() or not resolved.is_dir():
        resolved = fallback

    return GitOperations(resolved).repo_root or resolved


def workspace_root_from_context(ctx: InvokeContext | None) -> Path:
    if ctx is not None and ctx.workspace_root is not None:
        return canonical_workspace_root(ctx.workspace_root)

    if ctx is not None and ctx.session_dir is not None:
        if session_workspace := _session_workspace_root(ctx.session_dir):
            return session_workspace

    return canonical_workspace_root()


@lru_cache(maxsize=128)
def _session_workspace_root(session_dir: Path) -> Path | None:
    try:
        metadata = SessionLoader.load_metadata(session_dir)
    except ValueError:
        return None

    working_directory = metadata.environment.get("working_directory")
    if not working_directory:
        return None

    return canonical_workspace_root(working_directory)
