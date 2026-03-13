"""Compatibility registry backed by the native Malibu tool package."""

from __future__ import annotations

from typing import Any

from ._compat import build_native_tools, filter_tools

_FILE_TOOL_NAMES = {
    "read_file",
    "write_file",
    "edit_file",
    "ls",
    "grep",
    "apply_patch",
    "ast_grep",
    "str_replace",
    "lsp",
}
_WEB_TOOL_NAMES = {
    "web_search",
    "web_batch_search",
    "web_visit",
    "web_visit_compress",
    "image_search",
    "read_remote_image",
}
_MEDIA_TOOL_NAMES = {"generate_image", "generate_video"}
_PRODUCTIVITY_TOOL_NAMES = {"write_todos"}
_GIT_PREFIXES = ("git_",)
_SHELL_PREFIXES = ("shell_",)
_BROWSER_PREFIXES = ("browser_",)


def _resolve_tools(
    workspace_path: str | None = None,
    credential: dict[str, Any] | None = None,
) -> list[Any]:
    return build_native_tools(workspace_path=workspace_path, credential=credential)


def get_langchain_browser_tools(browser: Any | None = None) -> list[Any]:  # noqa: ARG001
    return filter_tools(_resolve_tools(), prefixes=_BROWSER_PREFIXES)


def get_langchain_shell_tools(
    shell_manager: Any | None = None,  # noqa: ARG001
    workspace_manager: Any | None = None,  # noqa: ARG001
) -> list[Any]:
    return filter_tools(_resolve_tools(), prefixes=_SHELL_PREFIXES)


def get_langchain_file_tools(
    sandbox: Any | None = None,  # noqa: ARG001
    workspace_manager: Any | None = None,  # noqa: ARG001
) -> list[Any]:
    return filter_tools(_resolve_tools(), names=_FILE_TOOL_NAMES)


def get_langchain_web_tools(credential: dict[str, Any]) -> list[Any]:
    return filter_tools(
        _resolve_tools(credential=credential),
        names=_WEB_TOOL_NAMES,
    )


def get_langchain_media_tools(credential: dict[str, Any]) -> list[Any]:
    return filter_tools(
        _resolve_tools(credential=credential),
        names=_MEDIA_TOOL_NAMES,
    )


def get_langchain_productivity_tools(
    sandbox: Any | None = None,  # noqa: ARG001
) -> list[Any]:
    return filter_tools(_resolve_tools(), names=_PRODUCTIVITY_TOOL_NAMES)


def get_langchain_dev_tools(
    sandbox: Any | None = None,  # noqa: ARG001
    workspace_manager: Any | None = None,  # noqa: ARG001
    credential: dict[str, Any] | None = None,
) -> list[Any]:
    return filter_tools(
        _resolve_tools(credential=credential),
        names=set(),
        prefixes=_GIT_PREFIXES,
    )


def get_langchain_agent_tools() -> list[Any]:
    return []


def get_all_langchain_tools(
    workspace_path: str,
    credential: dict[str, Any],
    sandbox: Any | None = None,  # noqa: ARG001
    browser: Any | None = None,  # noqa: ARG001
    workspace_manager: Any | None = None,  # noqa: ARG001
    shell_manager: Any | None = None,  # noqa: ARG001
    include_browser: bool = True,
    include_shell: bool = True,
    include_file: bool = True,
    include_web: bool = True,
    include_media: bool = True,
    include_productivity: bool = True,
    include_dev: bool = True,
    include_agent: bool = True,
) -> list[Any]:
    """Return the native tool bundle, optionally filtered by legacy flags."""

    tools = _resolve_tools(workspace_path=workspace_path, credential=credential)
    allowed_names = set()
    allowed_prefixes: list[str] = []

    if include_browser:
        allowed_prefixes.extend(_BROWSER_PREFIXES)
    if include_shell:
        allowed_prefixes.extend(_SHELL_PREFIXES)
        allowed_names.add("execute")
    if include_file:
        allowed_names.update(_FILE_TOOL_NAMES)
    if include_web:
        allowed_names.update(_WEB_TOOL_NAMES)
    if include_media:
        allowed_names.update(_MEDIA_TOOL_NAMES)
    if include_productivity:
        allowed_names.update(_PRODUCTIVITY_TOOL_NAMES)
    if include_dev:
        allowed_prefixes.extend(_GIT_PREFIXES)
    if include_agent:
        allowed_names.update(set())

    if not allowed_names and not allowed_prefixes:
        return []

    return filter_tools(
        tools,
        names=allowed_names,
        prefixes=tuple(allowed_prefixes),
    )


__all__ = [
    "get_all_langchain_tools",
    "get_langchain_agent_tools",
    "get_langchain_browser_tools",
    "get_langchain_dev_tools",
    "get_langchain_file_tools",
    "get_langchain_media_tools",
    "get_langchain_productivity_tools",
    "get_langchain_shell_tools",
    "get_langchain_web_tools",
]
