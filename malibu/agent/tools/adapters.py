from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Optional, Type

from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool as LangChainBaseTool
from pydantic import BaseModel, ConfigDict, Field, create_model


def json_schema_to_pydantic_model(
    name: str,
    schema: dict[str, Any],
) -> Type[BaseModel]:
    """Convert a JSON-schema-like dict into a Pydantic args schema."""

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    type_mapping: dict[str, Any] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    fields: dict[str, tuple[Any, Field]] = {}
    for field_name, field_schema in properties.items():
        json_type = field_schema.get("type", "string")
        python_type = type_mapping.get(json_type, Any)

        if json_type == "array" and "items" in field_schema:
            item_type = type_mapping.get(
                field_schema["items"].get("type", "string"),
                Any,
            )
            python_type = list[item_type]

        default = field_schema.get("default", ...)
        if field_name not in required:
            if default is ...:
                default = None
            python_type = Optional[python_type]

        fields[field_name] = (
            python_type,
            Field(default=default, description=field_schema.get("description", "")),
        )

    return create_model(f"{name}Input", **fields)


class ProjectToolAdapter(LangChainBaseTool):
    """Wrap a tool-server BaseTool as a LangChain tool."""

    name: str
    description: str
    args_schema: Type[BaseModel]
    response_format: str = "content"

    wrapped_tool: Any = Field(exclude=True)
    include_artifact: bool = Field(default=False, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @classmethod
    def from_project_tool(
        cls,
        tool: Any,
        *,
        name: str | None = None,
        description: str | None = None,
        include_artifact: bool = False,
    ) -> "ProjectToolAdapter":
        tool_name = name or tool.name
        args_schema = json_schema_to_pydantic_model(tool_name, tool.input_schema)
        return cls(
            name=tool_name,
            description=description or tool.description,
            args_schema=args_schema,
            response_format="content_and_artifact" if include_artifact else "content",
            wrapped_tool=tool,
            include_artifact=include_artifact,
        )

    def _run_async(self, kwargs: dict[str, Any]) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.wrapped_tool.execute(kwargs))
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, self.wrapped_tool.execute(kwargs))
            return future.result()

    def _format_result(self, result: Any) -> tuple[str, dict[str, Any] | None]:
        from malibu.agent.tool_server.tools.base import ImageContent, TextContent

        llm_content = result.llm_content
        artifact: dict[str, Any] | None = None

        if isinstance(llm_content, str):
            content = llm_content
            if self.include_artifact and result.user_display_content is not None:
                artifact = {
                    "display_content": result.user_display_content,
                    "is_error": bool(result.is_error),
                }
        elif isinstance(llm_content, list):
            text_parts: list[str] = []
            images: list[dict[str, Any]] = []
            for item in llm_content:
                if isinstance(item, TextContent):
                    text_parts.append(item.text)
                elif isinstance(item, ImageContent):
                    images.append(
                        {
                            "type": "image",
                            "data": item.data,
                            "mime_type": item.mime_type,
                        }
                    )

            content = "\n".join(part for part in text_parts if part).strip()
            if not content:
                content = "[image content]"

            if self.include_artifact:
                artifact = {
                    "images": images,
                    "display_content": result.user_display_content,
                    "is_error": bool(result.is_error),
                }
        else:
            content = str(llm_content)

        return content, artifact

    def _run(
        self,
        run_manager: CallbackManagerForToolRun | None = None,
        **kwargs: Any,
    ) -> Any:
        result = self._run_async(kwargs)
        content, artifact = self._format_result(result)
        if self.include_artifact:
            return content, artifact
        return content

    async def _arun(
        self,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
        **kwargs: Any,
    ) -> Any:
        result = await self.wrapped_tool.execute(kwargs)
        content, artifact = self._format_result(result)
        if self.include_artifact:
            return content, artifact
        return content
