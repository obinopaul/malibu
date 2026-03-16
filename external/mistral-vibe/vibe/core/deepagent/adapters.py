from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
import json
from typing import TYPE_CHECKING, Any, Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from vibe.core.llm.format import ResolvedToolCall
from vibe.core.types import (
    AvailableFunction,
    AvailableTool,
    LLMChunk,
    LLMMessage,
    LLMUsage,
    Role,
    ToolResultEvent,
)

if TYPE_CHECKING:
    from vibe.core.agent_loop import AgentLoop
    from vibe.core.types import BaseEvent

try:
    from langchain.tools import InjectedToolCallId, tool as langchain_tool
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import (
        AIMessage,
        AIMessageChunk,
        BaseMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )
    from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
    from langchain_core.utils.function_calling import convert_to_openai_tool

    LANGCHAIN_AVAILABLE = True
except ModuleNotFoundError:
    LANGCHAIN_AVAILABLE = False


def _extract_text_content(content: object) -> str:
    match content:
        case str():
            return content
        case list():
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif isinstance(block, str):
                    parts.append(block)
            return "".join(parts)
        case _:
            return ""


def _extract_reasoning_content(content: object) -> str | None:
    if not isinstance(content, list):
        return None
    parts = [
        block["text"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") in {"reasoning", "thinking"}
        and isinstance(block.get("text"), str)
    ]
    return "".join(parts) or None


def _tool_choice_to_vibe(
    tool_choice: object,
) -> str | AvailableTool | None:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        return tool_choice
    if not isinstance(tool_choice, dict):
        return None

    function = tool_choice.get("function", tool_choice)
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return None

    return AvailableTool(
        function=AvailableFunction(
            name=name,
            description=str(function.get("description", "")),
            parameters=function.get("parameters", {}),
        )
    )


def _tools_to_vibe(raw_tools: object) -> list[AvailableTool] | None:
    if not isinstance(raw_tools, list):
        return None

    converted: list[AvailableTool] = []
    for raw_tool in raw_tools:
        if not isinstance(raw_tool, dict):
            continue
        function = raw_tool.get("function", raw_tool)
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        converted.append(
            AvailableTool(
                function=AvailableFunction(
                    name=name,
                    description=str(function.get("description", "")),
                    parameters=function.get("parameters", {}),
                )
            )
        )
    return converted or None


def _tool_to_openai_schema(raw_tool: object) -> dict[str, Any] | None:
    if LANGCHAIN_AVAILABLE:
        try:
            converted = convert_to_openai_tool(raw_tool)
        except Exception:
            converted = None
        if isinstance(converted, dict):
            return converted

    if isinstance(raw_tool, dict):
        if "function" in raw_tool:
            return raw_tool
        name = raw_tool.get("name")
        if not isinstance(name, str) or not name:
            return None
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": str(raw_tool.get("description", "")),
                "parameters": raw_tool.get("parameters", {}),
            },
        }

    name = getattr(raw_tool, "name", None)
    if not isinstance(name, str) or not name:
        return None

    args_schema = getattr(raw_tool, "args_schema", None)
    parameters = (
        args_schema.model_json_schema()
        if isinstance(args_schema, type) and issubclass(args_schema, BaseModel)
        else {}
    )
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": str(getattr(raw_tool, "description", "")),
            "parameters": parameters,
        },
    }


def _langchain_tool_calls_to_vibe(tool_calls: object) -> list[dict[str, Any]] | None:
    if not isinstance(tool_calls, list):
        return None

    converted: list[dict[str, Any]] = []
    for index, tool_call in enumerate(tool_calls):
        if not isinstance(tool_call, dict):
            continue
        name = tool_call.get("name")
        if not isinstance(name, str) or not name:
            continue
        arguments = tool_call.get("args", {})
        converted.append(
            {
                "id": str(tool_call.get("id") or uuid4()),
                "index": index,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": (
                        arguments
                        if isinstance(arguments, str)
                        else json.dumps(arguments, ensure_ascii=False)
                    ),
                },
            }
        )
    return converted or None


def _vibe_to_langchain_ai_message(message: LLMMessage, usage: LLMUsage | None = None):
    if not LANGCHAIN_AVAILABLE:
        msg = "LangChain is not installed"
        raise ModuleNotFoundError(msg)

    tool_calls = []
    for tool_call in message.tool_calls or []:
        args = tool_call.function.arguments or "{}"
        try:
            parsed_args = json.loads(args)
        except json.JSONDecodeError:
            parsed_args = args
        tool_calls.append(
            {
                "id": tool_call.id,
                "name": tool_call.function.name,
                "args": parsed_args,
                "type": "tool_call",
            }
        )

    kwargs: dict[str, Any] = {"content": message.content or "", "tool_calls": tool_calls}
    if message.reasoning_content:
        kwargs["additional_kwargs"] = {"reasoning_content": message.reasoning_content}
    if usage is not None:
        kwargs["usage_metadata"] = {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "total_tokens": usage.prompt_tokens + usage.completion_tokens,
        }
    return AIMessage(**kwargs)


def _vibe_to_langchain_ai_chunk(message: LLMMessage, usage: LLMUsage | None = None):
    if not LANGCHAIN_AVAILABLE:
        msg = "LangChain is not installed"
        raise ModuleNotFoundError(msg)

    tool_call_chunks = []
    for tool_call in message.tool_calls or []:
        tool_call_chunks.append(
            {
                "id": tool_call.id,
                "name": tool_call.function.name,
                "args": tool_call.function.arguments or "",
                "index": tool_call.index,
                "type": "tool_call_chunk",
            }
        )

    kwargs: dict[str, Any] = {
        "content": message.content or "",
        "tool_call_chunks": tool_call_chunks,
    }
    if message.reasoning_content:
        kwargs["additional_kwargs"] = {"reasoning_content": message.reasoning_content}
    if usage is not None:
        kwargs["usage_metadata"] = {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "total_tokens": usage.prompt_tokens + usage.completion_tokens,
        }
    return AIMessageChunk(**kwargs)


def langchain_messages_to_vibe(messages: Sequence[BaseMessage]) -> list[LLMMessage]:
    if not LANGCHAIN_AVAILABLE:
        msg = "LangChain is not installed"
        raise ModuleNotFoundError(msg)

    converted: list[LLMMessage] = []
    for message in messages:
        match message:
            case SystemMessage():
                converted.append(LLMMessage(role=Role.system, content=_extract_text_content(message.content)))
            case HumanMessage():
                converted.append(LLMMessage(role=Role.user, content=_extract_text_content(message.content)))
            case ToolMessage():
                converted.append(
                    LLMMessage(
                        role=Role.tool,
                        content=_extract_text_content(message.content),
                        tool_call_id=message.tool_call_id,
                        name=getattr(message, "name", None),
                    )
                )
            case AIMessage():
                converted.append(
                    LLMMessage(
                        role=Role.assistant,
                        content=_extract_text_content(message.content),
                        reasoning_content=(
                            getattr(message, "additional_kwargs", {}).get("reasoning_content")
                            or _extract_reasoning_content(message.content)
                        ),
                        tool_calls=_langchain_tool_calls_to_vibe(getattr(message, "tool_calls", None)),
                    )
                )
            case _:
                continue
    return converted


def vibe_messages_to_langchain(messages: Sequence[LLMMessage]) -> list[Any]:
    if not LANGCHAIN_AVAILABLE:
        msg = "LangChain is not installed"
        raise ModuleNotFoundError(msg)

    converted: list[Any] = []
    for message in messages:
        match message.role:
            case Role.system:
                converted.append(SystemMessage(content=message.content or ""))
            case Role.user:
                converted.append(HumanMessage(content=message.content or ""))
            case Role.assistant:
                converted.append(_vibe_to_langchain_ai_message(message))
            case Role.tool:
                converted.append(
                    ToolMessage(
                        content=message.content or "",
                        tool_call_id=message.tool_call_id or str(uuid4()),
                        name=message.name,
                    )
                )
    return converted


if LANGCHAIN_AVAILABLE:

    class VibeChatModel(BaseChatModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)

        loop: Any

        @property
        def _llm_type(self) -> str:
            return "vibe"

        @property
        def _identifying_params(self) -> dict[str, Any]:
            active_model = self.loop.config.get_active_model()
            provider = self.loop.config.get_provider_for_model(active_model)
            return {"model": active_model.name, "provider": provider.name}

        def _prepare_request(
            self,
            messages: Sequence[BaseMessage],
            kwargs: dict[str, Any],
        ) -> tuple[Any, Any, list[LLMMessage], list[AvailableTool] | None, str | AvailableTool | None, int | None]:
            active_model = self.loop.config.get_active_model()
            provider = self.loop.config.get_provider_for_model(active_model)
            vibe_messages = langchain_messages_to_vibe(messages)
            return (
                active_model,
                provider,
                vibe_messages,
                _tools_to_vibe(kwargs.get("tools")),
                _tool_choice_to_vibe(kwargs.get("tool_choice")),
                kwargs.get("max_tokens"),
            )

        def bind_tools(
            self, tools: Sequence[Any], *, tool_choice: object = None, **kwargs: Any
        ) -> Any:
            formatted_tools = [
                schema
                for raw_tool in tools
                if (schema := _tool_to_openai_schema(raw_tool)) is not None
            ]
            bound_kwargs = {
                **kwargs,
                "tools": formatted_tools,
                "tool_choice": tool_choice,
            }
            return self.bind(**bound_kwargs)

        def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:
            msg = "VibeChatModel only supports async generation"
            raise NotImplementedError(msg)

        async def _agenerate(
            self,
            messages: Sequence[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> ChatResult:
            del stop, run_manager
            model, provider, vibe_messages, tools, tool_choice, max_tokens = (
                self._prepare_request(messages, kwargs)
            )
            result = await self.loop.backend.complete(
                model=model,
                messages=vibe_messages,
                temperature=kwargs.get("temperature", model.temperature),
                tools=tools,
                tool_choice=tool_choice,
                extra_headers=self.loop._get_extra_headers(provider),
                max_tokens=max_tokens,
                metadata=(
                    self.loop.entrypoint_metadata.model_dump()
                    if self.loop.entrypoint_metadata
                    else None
                ),
            )
            ai_message = _vibe_to_langchain_ai_message(result.message, result.usage)
            return ChatResult(generations=[ChatGeneration(message=ai_message)])

        async def _astream(
            self,
            messages: Sequence[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> AsyncGenerator[ChatGenerationChunk, None]:
            del stop, run_manager
            model, provider, vibe_messages, tools, tool_choice, max_tokens = (
                self._prepare_request(messages, kwargs)
            )
            async for chunk in self.loop.backend.complete_streaming(
                model=model,
                messages=vibe_messages,
                temperature=kwargs.get("temperature", model.temperature),
                tools=tools,
                tool_choice=tool_choice,
                extra_headers=self.loop._get_extra_headers(provider),
                max_tokens=max_tokens,
                metadata=(
                    self.loop.entrypoint_metadata.model_dump()
                    if self.loop.entrypoint_metadata
                    else None
                ),
            ):
                yield ChatGenerationChunk(
                    message=_vibe_to_langchain_ai_chunk(chunk.message, chunk.usage)
                )

else:

    class VibeChatModel:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            msg = "LangChain is not installed"
            raise ModuleNotFoundError(msg)


async def _invoke_vibe_tool(
    loop: AgentLoop,
    tool_name: str,
    tool_class: type[Any],
    args_model: type[BaseModel],
    kwargs: dict[str, Any],
    tool_call_id: str,
    emit_event: Callable[[BaseEvent], Awaitable[None]],
    on_tool_started: Callable[[], None],
    on_tool_finished: Callable[[], None],
) -> str:
    on_tool_started()
    try:
        validated_args = args_model.model_validate(kwargs)
        resolved_tool_call = ResolvedToolCall(
            tool_name=tool_name,
            tool_class=tool_class,
            validated_args=validated_args,
            call_id=tool_call_id,
        )

        final_event: ToolResultEvent | None = None
        async for event in loop._process_one_tool_call(resolved_tool_call):
            await emit_event(event)
            if isinstance(event, ToolResultEvent):
                final_event = event

        if final_event is None:
            return ""
        if final_event.result is not None:
            return "\n".join(
                f"{key}: {value}"
                for key, value in final_event.result.model_dump().items()
            )
        if final_event.skip_reason:
            return final_event.skip_reason
        return final_event.error or ""
    finally:
        on_tool_finished()


def build_langchain_tools(
    loop: AgentLoop,
    emit_event: Callable[[BaseEvent], Awaitable[None]],
    on_tool_started: Callable[[], None],
    on_tool_finished: Callable[[], None],
) -> list[Any]:
    if not LANGCHAIN_AVAILABLE:
        msg = "LangChain is not installed"
        raise ModuleNotFoundError(msg)

    tools: list[Any] = []
    for tool_name, tool_class in loop.tool_manager.available_tools.items():
        args_model, _ = tool_class._get_tool_args_results()

        def _make_runner(
            *,
            current_tool_name: str,
            current_tool_class: type[Any],
            current_args_model: type[BaseModel],
        ) -> Any:
            async def _runner(
                tool_call_id: Annotated[str | None, InjectedToolCallId] = None,
                **kwargs: Any,
            ) -> str:
                return await _invoke_vibe_tool(
                    loop=loop,
                    tool_name=current_tool_name,
                    tool_class=current_tool_class,
                    args_model=current_args_model,
                    kwargs=kwargs,
                    tool_call_id=tool_call_id or str(uuid4()),
                    emit_event=emit_event,
                    on_tool_started=on_tool_started,
                    on_tool_finished=on_tool_finished,
                )

            _runner.__name__ = f"run_{current_tool_name.replace('-', '_')}"
            return langchain_tool(
                current_tool_name,
                description=current_tool_class.description,
                args_schema=current_args_model,
            )(_runner)

        tools.append(
            _make_runner(
                current_tool_name=tool_name,
                current_tool_class=tool_class,
                current_args_model=args_model,
            )
        )
    return tools
