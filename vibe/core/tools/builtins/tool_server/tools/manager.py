"""Compatibility helpers for legacy tool-server entrypoints."""

from __future__ import annotations

from typing import Any

from ._compat import build_native_tools


def get_common_tools(
    sandbox: Any | None = None,  # noqa: ARG001
    *,
    workspace_path: str | None = None,
    credential: dict[str, Any] | None = None,
) -> list[Any]:
    """Return the native tool bundle for legacy common-tool callers."""

    return build_native_tools(workspace_path=workspace_path, credential=credential)


def get_sandbox_tools(workspace_path: str, credential: dict[str, Any]) -> list[Any]:
    """Return the native tool bundle for legacy sandbox-tool callers."""

    return build_native_tools(workspace_path=workspace_path, credential=credential)


def get_langchain_tools(workspace_path: str, credential: dict[str, Any]) -> list[Any]:
    """Return native LangChain tools for legacy callers."""

    return build_native_tools(workspace_path=workspace_path, credential=credential)


__all__ = ["get_common_tools", "get_langchain_tools", "get_sandbox_tools"]
