from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Sequence
import json
import os
import types
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple

import httpx

from vibe.core.llm.backend.anthropic import AnthropicAdapter
from vibe.core.llm.backend.base import APIAdapter, PreparedRequest
from vibe.core.llm.backend.reasoning_adapter import ReasoningAdapter
from vibe.core.llm.backend.vertex import VertexAnthropicAdapter
from vibe.core.llm.exceptions import BackendErrorBuilder
from vibe.core.llm.message_utils import merge_consecutive_user_messages
from vibe.core.types import (
    AvailableTool,
    FunctionCall,
    LLMChunk,
    LLMMessage,
    LLMUsage,
    Role,
    StrToolChoice,
    ToolCall,
)
from vibe.core.utils import async_generator_retry, async_retry

if TYPE_CHECKING:
    from vibe.core.config import ModelConfig, ProviderConfig


_OPENAI_TOOL_NAME_MAX_LEN = 128


def _clamp_tool_name(name: str | None) -> str:
    if not name:
        return ""
    return name[:_OPENAI_TOOL_NAME_MAX_LEN]


class OpenAIAdapter(APIAdapter):
    endpoint: ClassVar[str] = "/chat/completions"

    def build_payload(
        self,
        model_name: str,
        converted_messages: list[dict[str, Any]],
        temperature: float,
        tools: list[AvailableTool] | None,
        max_tokens: int | None,
        tool_choice: StrToolChoice | AvailableTool | None,
    ) -> dict[str, Any]:
        payload = {
            "model": model_name,
            "messages": converted_messages,
            "temperature": temperature,
        }

        if tools:
            payload["tools"] = [
                {
                    **tool.model_dump(exclude_none=True),
                    "function": {
                        **tool.function.model_dump(exclude_none=True),
                        "name": _clamp_tool_name(tool.function.name),
                    },
                }
                for tool in tools
            ]
        if tool_choice:
            payload["tool_choice"] = (
                tool_choice
                if isinstance(tool_choice, str)
                else {
                    **tool_choice.model_dump(),
                    "function": {
                        **tool_choice.function.model_dump(),
                        "name": _clamp_tool_name(tool_choice.function.name),
                    },
                }
            )
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        return payload

    def build_headers(self, api_key: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _reasoning_to_api(
        self, msg_dict: dict[str, Any], field_name: str
    ) -> dict[str, Any]:
        if field_name != "reasoning_content" and "reasoning_content" in msg_dict:
            msg_dict[field_name] = msg_dict.pop("reasoning_content")
        return msg_dict

    def _reasoning_from_api(
        self, msg_dict: dict[str, Any], field_name: str
    ) -> dict[str, Any]:
        if field_name != "reasoning_content" and field_name in msg_dict:
            msg_dict["reasoning_content"] = msg_dict.pop(field_name)
        return msg_dict

    def prepare_request(  # noqa: PLR0913
        self,
        *,
        model_name: str,
        messages: Sequence[LLMMessage],
        temperature: float,
        tools: list[AvailableTool] | None,
        max_tokens: int | None,
        tool_choice: StrToolChoice | AvailableTool | None,
        enable_streaming: bool,
        provider: ProviderConfig,
        api_key: str | None = None,
        thinking: str = "off",
    ) -> PreparedRequest:
        merged_messages = merge_consecutive_user_messages(messages)
        field_name = provider.reasoning_field_name
        converted_messages = [
            self._reasoning_to_api(
                msg.model_dump(exclude_none=True, exclude={"message_id"}), field_name
            )
            for msg in merged_messages
        ]

        for converted in converted_messages:
            if converted.get("role") == "tool" and isinstance(converted.get("name"), str):
                converted["name"] = _clamp_tool_name(converted.get("name"))

            tool_calls = converted.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function_block = tool_call.get("function")
                    if not isinstance(function_block, dict):
                        continue
                    function_block["name"] = _clamp_tool_name(
                        function_block.get("name")
                    )

        payload = self.build_payload(
            model_name, converted_messages, temperature, tools, max_tokens, tool_choice
        )

        if enable_streaming:
            payload["stream"] = True
            stream_options = {"include_usage": True}
            if provider.name == "mistral":
                stream_options["stream_tool_calls"] = True
            payload["stream_options"] = stream_options

        headers = self.build_headers(api_key)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        return PreparedRequest(self.endpoint, headers, body)

    def _parse_message(
        self, data: dict[str, Any], field_name: str
    ) -> LLMMessage | None:
        if data.get("choices"):
            choice = data["choices"][0]
            if "message" in choice:
                msg_dict = self._reasoning_from_api(choice["message"], field_name)
                return LLMMessage.model_validate(msg_dict)
            if "delta" in choice:
                msg_dict = self._reasoning_from_api(choice["delta"], field_name)
                return LLMMessage.model_validate(msg_dict)
            raise ValueError("Invalid response data: missing message or delta")

        if "message" in data:
            msg_dict = self._reasoning_from_api(data["message"], field_name)
            return LLMMessage.model_validate(msg_dict)
        if "delta" in data:
            msg_dict = self._reasoning_from_api(data["delta"], field_name)
            return LLMMessage.model_validate(msg_dict)

        return None

    def parse_response(
        self, data: dict[str, Any], provider: ProviderConfig
    ) -> LLMChunk:
        message = self._parse_message(data, provider.reasoning_field_name)
        if message is None:
            message = LLMMessage(role=Role.assistant, content="")

        usage_data = data.get("usage") or {}
        usage = LLMUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
        )

        return LLMChunk(message=message, usage=usage)


class OpenAIResponsesAdapter(APIAdapter):
    endpoint: ClassVar[str] = "/responses"

    def __init__(self) -> None:
        self._function_call_state: dict[int, dict[str, Any]] = {}
        self._streaming_request_enabled = False
        self._seen_text_delta = False
        self._seen_reasoning_delta = False
        self._seen_tool_call_event = False

    @staticmethod
    def _tool_to_api(tool: AvailableTool) -> dict[str, Any]:
        return {
            "type": tool.type,
            "name": _clamp_tool_name(tool.function.name),
            "description": tool.function.description,
            "parameters": tool.function.parameters,
        }

    @staticmethod
    def _supports_temperature(model_name: str, thinking: str) -> bool:
        normalized_name = model_name.lower()
        if not normalized_name.startswith("gpt-5"):
            return True
        if normalized_name.startswith(("gpt-5.1", "gpt-5.2")):
            return thinking == "off"
        return False

    def _tool_choice_to_api(
        self, tool_choice: StrToolChoice | AvailableTool | None
    ) -> str | dict[str, Any] | None:
        if tool_choice is None or isinstance(tool_choice, str):
            return tool_choice
        return {"type": "function", "name": _clamp_tool_name(tool_choice.function.name)}

    def _convert_assistant_message(self, msg: LLMMessage) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if msg.content:
            items.append({"role": "assistant", "content": msg.content})
        for tool_call in msg.tool_calls or []:
            items.append(
                {
                    "type": "function_call",
                    "call_id": tool_call.id or "",
                    "name": _clamp_tool_name(tool_call.function.name),
                    "arguments": tool_call.function.arguments or "",
                }
            )
        return items

    def _convert_message(self, msg: LLMMessage) -> list[dict[str, Any]]:
        match msg.role:
            case Role.user:
                return [{"role": "user", "content": msg.content or ""}]
            case Role.assistant:
                return self._convert_assistant_message(msg)
            case Role.tool:
                return [
                    {
                        "type": "function_call_output",
                        "call_id": msg.tool_call_id or "",
                        "output": msg.content or "",
                    }
                ]
            case Role.system:
                return []

    @staticmethod
    def _usage_from_data(data: dict[str, Any]) -> LLMUsage:
        usage_data = data.get("usage") or data.get("response", {}).get("usage") or {}
        return LLMUsage(
            prompt_tokens=usage_data.get("input_tokens")
            or usage_data.get("prompt_tokens")
            or 0,
            completion_tokens=usage_data.get("output_tokens")
            or usage_data.get("completion_tokens")
            or 0,
        )

    @staticmethod
    def _reasoning_summary_from_item(item: dict[str, Any]) -> str | None:
        summary = item.get("summary")
        if isinstance(summary, str):
            return summary or None
        if isinstance(summary, list):
            text_parts = [
                str(part.get("text", ""))
                for part in summary
                if isinstance(part, dict) and part.get("text")
            ]
            if text_parts:
                return "".join(text_parts)
        if isinstance(content := item.get("content"), str) and content:
            return content
        return None

    @staticmethod
    def _text_from_message_item(item: dict[str, Any]) -> str | None:
        content = item.get("content")
        if isinstance(content, str):
            return content or None
        if not isinstance(content, list):
            return None

        text_parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            match part.get("type"):
                case "output_text" | "text":
                    if text := part.get("text"):
                        text_parts.append(str(text))
        return "".join(text_parts) or None

    def _remember_function_call(
        self, output_index: int, item: dict[str, Any]
    ) -> dict[str, Any]:
        state = self._function_call_state.setdefault(output_index, {})
        if call_id := item.get("call_id") or item.get("id"):
            state["id"] = call_id
        if name := item.get("name"):
            state["name"] = _clamp_tool_name(name)
        if item_id := item.get("id"):
            state["item_id"] = item_id
        return state

    def _tool_call_chunk(
        self,
        *,
        output_index: int,
        item: dict[str, Any] | None = None,
        arguments: str | None = None,
        include_name: bool = True,
    ) -> LLMChunk:
        resolved_item = item or {}
        state = self._remember_function_call(output_index, resolved_item)
        # Only include the tool name and id on the FIRST chunk for each tool
        # call.  LangChain's AIMessageChunk.__add__ concatenates string fields
        # across chunks, so sending the name on every delta produces mangled
        # names like "read_fileread_fileread_file..." which breaks ToolNode
        # lookup.  The id field suffers the same concatenation problem.
        tool_call = ToolCall(
            id=str(state.get("id") or "") if include_name else "",
            index=output_index,
            function=FunctionCall(
                name=state.get("name") if include_name else "",
                arguments=arguments if arguments is not None else "",
            ),
        )
        return LLMChunk(
            message=LLMMessage(role=Role.assistant, tool_calls=[tool_call]),
            usage=LLMUsage(),
        )

    @staticmethod
    def _empty_chunk(usage: LLMUsage | None = None) -> LLMChunk:
        return LLMChunk(
            message=LLMMessage(role=Role.assistant, content=""),
            usage=usage or LLMUsage(),
        )

    def prepare_request(  # noqa: PLR0913
        self,
        *,
        model_name: str,
        messages: Sequence[LLMMessage],
        temperature: float,
        tools: list[AvailableTool] | None,
        max_tokens: int | None,
        tool_choice: StrToolChoice | AvailableTool | None,
        enable_streaming: bool,
        provider: ProviderConfig,
        api_key: str | None = None,
        thinking: str = "off",
    ) -> PreparedRequest:
        del provider
        self._function_call_state.clear()
        self._streaming_request_enabled = enable_streaming
        self._seen_text_delta = False
        self._seen_reasoning_delta = False
        self._seen_tool_call_event = False

        merged_messages = merge_consecutive_user_messages(messages)
        instructions_parts = [
            msg.content or "" for msg in merged_messages if msg.role == Role.system
        ]
        input_items = [
            item
            for msg in merged_messages
            if msg.role != Role.system
            for item in self._convert_message(msg)
        ]

        payload: dict[str, Any] = {
            "model": model_name,
            "input": input_items,
        }

        if self._supports_temperature(model_name, thinking):
            payload["temperature"] = temperature

        if instructions_parts:
            payload["instructions"] = "\n\n".join(
                part for part in instructions_parts if part
            )

        if thinking != "none":
            payload["reasoning"] = {"effort": thinking, "summary": "auto"}

        if tools:
            payload["tools"] = [self._tool_to_api(tool) for tool in tools]

        if converted_tool_choice := self._tool_choice_to_api(tool_choice):
            payload["tool_choice"] = converted_tool_choice

        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens

        if enable_streaming:
            payload["stream"] = True

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return PreparedRequest(self.endpoint, headers, body)

    def parse_response(
        self, data: dict[str, Any], provider: ProviderConfig
    ) -> LLMChunk:
        del provider
        event_type = str(data.get("type", ""))
        usage = self._usage_from_data(data)

        match event_type:
            case "response.output_text.delta":
                self._seen_text_delta = True
                return LLMChunk(
                    message=LLMMessage(
                        role=Role.assistant, content=str(data.get("delta", ""))
                    ),
                    usage=usage,
                )
            case "response.reasoning_summary_text.delta":
                self._seen_reasoning_delta = True
                return LLMChunk(
                    message=LLMMessage(
                        role=Role.assistant,
                        reasoning_content=str(data.get("delta", "")),
                    ),
                    usage=usage,
                )
            case "response.output_item.added":
                item = data.get("item") or {}
                if item.get("type") != "function_call":
                    return self._empty_chunk(usage)
                output_index = int(data.get("output_index", 0))
                self._seen_tool_call_event = True
                self._remember_function_call(output_index, item)
                return self._tool_call_chunk(
                    output_index=output_index, item=item, include_name=True,
                )
            case "response.function_call_arguments.delta":
                output_index = int(data.get("output_index", 0))
                self._seen_tool_call_event = True
                self._function_call_state.setdefault(output_index, {})[
                    "seen_argument_delta"
                ] = True
                state = self._function_call_state.setdefault(output_index, {})
                if call_id := data.get("call_id"):
                    state["id"] = call_id
                if name := data.get("name"):
                    state["name"] = _clamp_tool_name(name)
                return self._tool_call_chunk(
                    output_index=output_index,
                    arguments=str(data.get("delta", "")),
                    include_name=False,
                )
            case "response.output_item.done":
                item = data.get("item") or {}
                output_index = int(data.get("output_index", 0))
                match item.get("type"):
                    case "function_call":
                        self._seen_tool_call_event = True
                        state = self._remember_function_call(output_index, item)
                        if state.get("seen_argument_delta"):
                            return self._empty_chunk(usage)
                        # No argument deltas were streamed, so this is the
                        # only chunk — include name and full arguments.
                        return self._tool_call_chunk(
                            output_index=output_index,
                            item=item,
                            arguments=str(item.get("arguments", "")),
                            include_name=True,
                        )
                    case "reasoning":
                        if self._streaming_request_enabled and self._seen_reasoning_delta:
                            return self._empty_chunk(usage)
                        return LLMChunk(
                            message=LLMMessage(
                                role=Role.assistant,
                                reasoning_content=self._reasoning_summary_from_item(
                                    item
                                )
                                or "",
                            ),
                            usage=usage,
                        )
                    case "message":
                        if self._streaming_request_enabled and self._seen_text_delta:
                            return self._empty_chunk(usage)
                        return LLMChunk(
                            message=LLMMessage(
                                role=Role.assistant,
                                content=self._text_from_message_item(item) or "",
                            ),
                            usage=usage,
                        )
            case "response.completed":
                response = data.get("response") or {}
                output_items = response.get("output") or []
                text_parts: list[str] = []
                reasoning_parts: list[str] = []
                tool_calls: list[ToolCall] = []

                for output_index, item in enumerate(output_items):
                    match item.get("type"):
                        case "message":
                            if text := self._text_from_message_item(item):
                                text_parts.append(text)
                        case "reasoning":
                            if summary := self._reasoning_summary_from_item(item):
                                reasoning_parts.append(summary)
                        case "function_call":
                            tool_calls.append(
                                ToolCall(
                                    id=item.get("call_id") or item.get("id"),
                                    index=output_index,
                                    function=FunctionCall(
                                        name=item.get("name"),
                                        arguments=item.get("arguments", ""),
                                    ),
                                )
                            )

                if self._streaming_request_enabled:
                    if self._seen_text_delta:
                        text_parts.clear()
                    if self._seen_reasoning_delta:
                        reasoning_parts.clear()
                    if self._seen_tool_call_event:
                        tool_calls.clear()

                return LLMChunk(
                    message=LLMMessage(
                        role=Role.assistant,
                        content="".join(text_parts) or None,
                        reasoning_content="".join(reasoning_parts) or None,
                        tool_calls=tool_calls or None,
                    ),
                    usage=usage,
                )

        return self._empty_chunk(usage)


AdapterFactory = Callable[[], APIAdapter]


ADAPTER_FACTORIES: dict[str, AdapterFactory] = {
    "openai": OpenAIAdapter,
    "openai-responses": OpenAIResponsesAdapter,
    "anthropic": AnthropicAdapter,
    "vertex-anthropic": VertexAnthropicAdapter,
    "reasoning": ReasoningAdapter,
}


class GenericBackend:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        provider: ProviderConfig,
        timeout: float = 720.0,
    ) -> None:
        """Initialize the backend.

        Args:
            client: Optional httpx client to use. If not provided, one will be created.
        """
        self._client = client
        self._owns_client = client is None
        self._provider = provider
        self._timeout = timeout

    async def __aenter__(self) -> GenericBackend:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        if self._owns_client and self._client:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
            self._owns_client = True
        return self._client

    async def complete(
        self,
        *,
        model: ModelConfig,
        messages: Sequence[LLMMessage],
        temperature: float = 0.2,
        tools: list[AvailableTool] | None = None,
        max_tokens: int | None = None,
        tool_choice: StrToolChoice | AvailableTool | None = None,
        extra_headers: dict[str, str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> LLMChunk:
        api_key = (
            os.getenv(self._provider.api_key_env_var)
            if self._provider.api_key_env_var
            else None
        )

        api_style = getattr(self._provider, "api_style", "openai")
        adapter = ADAPTER_FACTORIES[api_style]()

        req = adapter.prepare_request(
            model_name=model.name,
            messages=messages,
            temperature=temperature,
            tools=tools,
            max_tokens=max_tokens,
            tool_choice=tool_choice,
            enable_streaming=False,
            provider=self._provider,
            api_key=api_key,
            thinking=model.thinking,
        )

        headers = req.headers
        if extra_headers:
            headers.update(extra_headers)

        base = req.base_url or self._provider.api_base
        url = f"{base}{req.endpoint}"

        try:
            res_data, _ = await self._make_request(url, req.body, headers)
            return adapter.parse_response(res_data, self._provider)

        except httpx.HTTPStatusError as e:
            raise BackendErrorBuilder.build_http_error(
                provider=self._provider.name,
                endpoint=url,
                response=e.response,
                headers=e.response.headers,
                model=model.name,
                messages=messages,
                temperature=temperature,
                has_tools=bool(tools),
                tool_choice=tool_choice,
            ) from e
        except httpx.RequestError as e:
            raise BackendErrorBuilder.build_request_error(
                provider=self._provider.name,
                endpoint=url,
                error=e,
                model=model.name,
                messages=messages,
                temperature=temperature,
                has_tools=bool(tools),
                tool_choice=tool_choice,
            ) from e

    async def complete_streaming(
        self,
        *,
        model: ModelConfig,
        messages: Sequence[LLMMessage],
        temperature: float = 0.2,
        tools: list[AvailableTool] | None = None,
        max_tokens: int | None = None,
        tool_choice: StrToolChoice | AvailableTool | None = None,
        extra_headers: dict[str, str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AsyncGenerator[LLMChunk, None]:
        api_key = (
            os.getenv(self._provider.api_key_env_var)
            if self._provider.api_key_env_var
            else None
        )

        api_style = getattr(self._provider, "api_style", "openai")
        adapter = ADAPTER_FACTORIES[api_style]()

        req = adapter.prepare_request(
            model_name=model.name,
            messages=messages,
            temperature=temperature,
            tools=tools,
            max_tokens=max_tokens,
            tool_choice=tool_choice,
            enable_streaming=True,
            provider=self._provider,
            api_key=api_key,
            thinking=model.thinking,
        )

        headers = req.headers
        if extra_headers:
            headers.update(extra_headers)

        base = req.base_url or self._provider.api_base
        url = f"{base}{req.endpoint}"

        try:
            async for res_data in self._make_streaming_request(url, req.body, headers):
                yield adapter.parse_response(res_data, self._provider)

        except httpx.HTTPStatusError as e:
            raise BackendErrorBuilder.build_http_error(
                provider=self._provider.name,
                endpoint=url,
                response=e.response,
                headers=e.response.headers,
                model=model.name,
                messages=messages,
                temperature=temperature,
                has_tools=bool(tools),
                tool_choice=tool_choice,
            ) from e
        except httpx.RequestError as e:
            raise BackendErrorBuilder.build_request_error(
                provider=self._provider.name,
                endpoint=url,
                error=e,
                model=model.name,
                messages=messages,
                temperature=temperature,
                has_tools=bool(tools),
                tool_choice=tool_choice,
            ) from e

    class HTTPResponse(NamedTuple):
        data: dict[str, Any]
        headers: dict[str, str]

    @async_retry(tries=3)
    async def _make_request(
        self, url: str, data: bytes, headers: dict[str, str]
    ) -> HTTPResponse:
        client = self._get_client()
        response = await client.post(url, content=data, headers=headers)
        response.raise_for_status()

        response_headers = dict(response.headers.items())
        response_body = response.json()
        return self.HTTPResponse(response_body, response_headers)

    @async_generator_retry(tries=3)
    async def _make_streaming_request(
        self, url: str, data: bytes, headers: dict[str, str]
    ) -> AsyncGenerator[dict[str, Any]]:
        client = self._get_client()
        async with client.stream(
            method="POST", url=url, content=data, headers=headers
        ) as response:
            if not response.is_success:
                await response.aread()
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip() == "":
                    continue

                DELIM_CHAR = ":"
                if f"{DELIM_CHAR} " not in line:
                    raise ValueError(
                        f"Stream chunk improperly formatted. "
                        f"Expected `key{DELIM_CHAR} value`, received `{line}`"
                    )
                delim_index = line.find(DELIM_CHAR)
                key = line[0:delim_index]
                value = line[delim_index + 2 :]

                if key != "data":
                    # This might be the case with openrouter, so we just ignore it
                    continue
                if value == "[DONE]":
                    return
                yield json.loads(value.strip())

    async def count_tokens(
        self,
        *,
        model: ModelConfig,
        messages: Sequence[LLMMessage],
        temperature: float = 0.0,
        tools: list[AvailableTool] | None = None,
        tool_choice: StrToolChoice | AvailableTool | None = None,
        extra_headers: dict[str, str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> int:
        probe_messages = list(messages)
        if not probe_messages or probe_messages[-1].role != Role.user:
            probe_messages.append(LLMMessage(role=Role.user, content=""))

        result = await self.complete(
            model=model,
            messages=probe_messages,
            temperature=temperature,
            tools=tools,
            max_tokens=16,  # Minimal amount for openrouter with openai models
            tool_choice=tool_choice,
            extra_headers=extra_headers,
        )
        if result.usage is None:
            raise ValueError("Missing usage in non streaming completion")

        return result.usage.prompt_tokens

    async def close(self) -> None:
        if self._owns_client and self._client:
            await self._client.aclose()
            self._client = None
