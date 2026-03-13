"""Compatibility shims for the old tool-server LangChain adapter API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from malibu.agent.tools.adapters import ProjectToolAdapter, json_schema_to_pydantic_model

from ._compat import build_native_tools


class AuthenticationContext(BaseModel):
    """Legacy auth container retained for import compatibility."""

    user_id: str | None = None
    token: str | None = None
    session_id: str | None = None
    permissions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class LangChainToolAdapter(ProjectToolAdapter):
    """Legacy adapter name kept as an alias over the native adapter."""

    @classmethod
    def from_base_tool(
        cls,
        tool: Any,
        auth_context: AuthenticationContext | None = None,  # noqa: ARG003
    ) -> "LangChainToolAdapter":
        adapted = ProjectToolAdapter.from_project_tool(tool)
        return cls(
            name=adapted.name,
            description=adapted.description,
            args_schema=adapted.args_schema,
            response_format=adapted.response_format,
            wrapped_tool=adapted.wrapped_tool,
            include_artifact=adapted.include_artifact,
        )


def adapt_tools_for_langchain(
    tools: list[Any],
    auth_context: AuthenticationContext | None = None,  # noqa: ARG003
) -> list[LangChainToolAdapter]:
    """Adapt tool-server BaseTool objects into LangChain tools."""

    return [LangChainToolAdapter.from_base_tool(tool) for tool in tools]


def get_langchain_tools(
    workspace_path: str,
    credential: dict[str, Any],
    auth_context: AuthenticationContext | None = None,  # noqa: ARG003
) -> list[Any]:
    """Return the native Malibu tool bundle for legacy callers."""

    return build_native_tools(workspace_path=workspace_path, credential=credential)


__all__ = [
    "AuthenticationContext",
    "LangChainToolAdapter",
    "adapt_tools_for_langchain",
    "get_langchain_tools",
    "json_schema_to_pydantic_model",
]
