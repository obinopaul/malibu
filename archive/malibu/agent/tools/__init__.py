"""Native LangChain tools for the Malibu agent."""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from pathlib import Path

from malibu.config import get_settings

__all__ = [
    "ALL_TOOLS",
    "apply_patch",
    "ast_grep",
    "build_default_tools",
    "edit_file",
    "execute",
    "generate_image",
    "generate_video",
    "git_commit",
    "git_diff",
    "git_log",
    "git_status",
    "git_worktree_create",
    "git_worktree_list",
    "git_worktree_remove",
    "grep",
    "image_search",
    "ls",
    "lsp",
    "read_file",
    "read_remote_image",
    "shell_init",
    "shell_list",
    "shell_run",
    "shell_stop",
    "shell_view",
    "shell_write",
    "str_replace",
    "web_batch_search",
    "web_search",
    "web_visit",
    "web_visit_compress",
    "write_file",
    "write_todos",
]


def build_default_tools(*args, **kwargs):
    registry = import_module("malibu.agent.tools.registry")
    return registry.build_default_tools(*args, **kwargs)


@lru_cache(maxsize=1)
def _default_tools() -> list:
    return build_default_tools(
        settings=get_settings(),
        cwd=Path.cwd(),
        session_id="default",
    )


@lru_cache(maxsize=1)
def _tool_map() -> dict[str, object]:
    return {tool.name: tool for tool in _default_tools()}


def __getattr__(name: str):
    if name == "ALL_TOOLS":
        return _default_tools()
    if name in _tool_map():
        return _tool_map()[name]
    raise AttributeError(f"module 'malibu.agent.tools' has no attribute {name!r}")
