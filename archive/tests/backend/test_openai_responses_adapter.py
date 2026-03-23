from __future__ import annotations

import json

import pytest

from vibe.core.config import ProviderConfig
from vibe.core.llm.backend.generic import OpenAIResponsesAdapter
from vibe.core.types import (
    AvailableFunction,
    AvailableTool,
    FunctionCall,
    LLMChunk,
    LLMMessage,
    Role,
    ToolCall,
)


@pytest.fixture
def adapter() -> OpenAIResponsesAdapter:
    return OpenAIResponsesAdapter()


@pytest.fixture
def provider() -> ProviderConfig:
    return ProviderConfig(
        name="openai",
        api_base="https://api.openai.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        api_style="openai-responses",
    )


def _prepare(
    adapter: OpenAIResponsesAdapter,
    provider: ProviderConfig,
    messages: list[LLMMessage],
    **kwargs: object,
) -> dict[str, object]:
    defaults: dict[str, object] = {
        "model_name": "gpt-5",
        "messages": messages,
        "temperature": 0.2,
        "tools": None,
        "max_tokens": None,
        "tool_choice": "auto",
        "enable_streaming": False,
        "provider": provider,
        "api_key": "sk-test",
        "thinking": "medium",
    }
    defaults.update(kwargs)
    prepared = adapter.prepare_request(**defaults)
    return json.loads(prepared.body)


class TestPrepareRequest:
    def test_builds_responses_payload_with_instructions_and_reasoning(
        self, adapter: OpenAIResponsesAdapter, provider: ProviderConfig
    ) -> None:
        messages = [
            LLMMessage(role=Role.system, content="Follow instructions."),
            LLMMessage(role=Role.user, content="Hello"),
            LLMMessage(
                role=Role.assistant,
                tool_calls=[
                    ToolCall(
                        id="call_123",
                        index=0,
                        function=FunctionCall(
                            name="search", arguments='{"query":"hello"}'
                        ),
                    )
                ],
            ),
            LLMMessage(role=Role.tool, tool_call_id="call_123", content="result"),
        ]
        tools = [
            AvailableTool(
                function=AvailableFunction(
                    name="search",
                    description="Search",
                    parameters={"type": "object", "properties": {}},
                )
            )
        ]

        payload = _prepare(
            adapter,
            provider,
            messages,
            tools=tools,
            max_tokens=512,
            enable_streaming=True,
        )

        assert payload["model"] == "gpt-5"
        assert payload["instructions"] == "Follow instructions."
        assert payload["stream"] is True
        assert payload["max_output_tokens"] == 512
        assert payload["reasoning"] == {"effort": "medium", "summary": "auto"}
        assert payload["input"] == [
            {"role": "user", "content": "Hello"},
            {
                "type": "function_call",
                "call_id": "call_123",
                "name": "search",
                "arguments": '{"query":"hello"}',
            },
            {"type": "function_call_output", "call_id": "call_123", "output": "result"},
        ]
        assert payload["tools"][0] == {
            "type": "function",
            "name": "search",
            "description": "Search",
            "parameters": {"type": "object", "properties": {}},
        }

    def test_omits_reasoning_config_when_thinking_is_off(
        self, adapter: OpenAIResponsesAdapter, provider: ProviderConfig
    ) -> None:
        payload = _prepare(
            adapter,
            provider,
            [LLMMessage(role=Role.user, content="Hi")],
            thinking="none",
        )

        assert "reasoning" not in payload

    def test_omits_temperature_for_gpt_5_1_when_reasoning_enabled(
        self, adapter: OpenAIResponsesAdapter, provider: ProviderConfig
    ) -> None:
        payload = _prepare(
            adapter,
            provider,
            [LLMMessage(role=Role.user, content="Hi")],
            model_name="gpt-5.1",
            thinking="medium",
        )

        assert "temperature" not in payload

    def test_keeps_temperature_for_gpt_5_1_when_reasoning_is_off(
        self, adapter: OpenAIResponsesAdapter, provider: ProviderConfig
    ) -> None:
        payload = _prepare(
            adapter,
            provider,
            [LLMMessage(role=Role.user, content="Hi")],
            model_name="gpt-5.1",
            thinking="none",
            temperature=0.7,
        )

        assert payload["temperature"] == 0.7

    def test_omits_temperature_for_gpt_5_family_models_without_support(
        self, adapter: OpenAIResponsesAdapter, provider: ProviderConfig
    ) -> None:
        payload = _prepare(
            adapter,
            provider,
            [LLMMessage(role=Role.user, content="Hi")],
            model_name="gpt-5",
            thinking="none",
            temperature=0.7,
        )

        assert "temperature" not in payload

    def test_clamps_oversized_tool_names_in_responses_payload(
        self, adapter: OpenAIResponsesAdapter, provider: ProviderConfig
    ) -> None:
        long_name = "a" * 580
        messages = [
            LLMMessage(role=Role.user, content="todo"),
            LLMMessage(
                role=Role.assistant,
                tool_calls=[
                    ToolCall(
                        id="call_123",
                        index=0,
                        function=FunctionCall(name=long_name, arguments="{}"),
                    )
                ],
            ),
        ]
        tools = [
            AvailableTool(
                function=AvailableFunction(
                    name=long_name,
                    description="Long name tool",
                    parameters={"type": "object", "properties": {}},
                )
            )
        ]

        payload = _prepare(
            adapter,
            provider,
            messages,
            tools=tools,
            tool_choice=tools[0],
        )

        assert len(payload["input"][1]["name"]) == 128
        assert len(payload["tools"][0]["name"]) == 128
        assert len(payload["tool_choice"]["name"]) == 128


class TestParseResponse:
    def test_parses_output_text_delta(
        self, adapter: OpenAIResponsesAdapter, provider: ProviderConfig
    ) -> None:
        chunk = adapter.parse_response(
            {"type": "response.output_text.delta", "delta": "Hello"},
            provider,
        )
        assert chunk.message.content == "Hello"
        assert chunk.message.reasoning_content is None

    def test_parses_reasoning_summary_delta(
        self, adapter: OpenAIResponsesAdapter, provider: ProviderConfig
    ) -> None:
        chunk = adapter.parse_response(
            {"type": "response.reasoning_summary_text.delta", "delta": "Thinking..."},
            provider,
        )
        assert chunk.message.reasoning_content == "Thinking..."
        assert chunk.message.content == ""

    def test_tracks_function_call_added_and_argument_delta(
        self, adapter: OpenAIResponsesAdapter, provider: ProviderConfig
    ) -> None:
        added_chunk = adapter.parse_response(
            {
                "type": "response.output_item.added",
                "output_index": 1,
                "item": {
                    "id": "fc_1",
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "search",
                    "arguments": "",
                },
            },
            provider,
        )
        delta_chunk = adapter.parse_response(
            {
                "type": "response.function_call_arguments.delta",
                "output_index": 1,
                "delta": '{"query":"test"}',
            },
            provider,
        )

        assert added_chunk.message.tool_calls is not None
        assert added_chunk.message.tool_calls[0].id == "call_1"
        assert added_chunk.message.tool_calls[0].function.name == "search"

        assert delta_chunk.message.tool_calls is not None
        assert delta_chunk.message.tool_calls[0].index == 1
        assert delta_chunk.message.tool_calls[0].function.arguments == '{"query":"test"}'

    def test_parses_completed_response(
        self, adapter: OpenAIResponsesAdapter, provider: ProviderConfig
    ) -> None:
        chunk = adapter.parse_response(
            {
                "type": "response.completed",
                "response": {
                    "output": [
                        {
                            "type": "reasoning",
                            "summary": [{"type": "summary_text", "text": "First"}],
                        },
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "Answer"}],
                        },
                        {
                            "type": "function_call",
                            "call_id": "call_7",
                            "name": "search",
                            "arguments": '{"query":"x"}',
                        },
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            },
            provider,
        )

        assert chunk.message.reasoning_content == "First"
        assert chunk.message.content == "Answer"
        assert chunk.message.tool_calls is not None
        assert chunk.message.tool_calls[0].id == "call_7"
        assert chunk.usage is not None
        assert chunk.usage.prompt_tokens == 10
        assert chunk.usage.completion_tokens == 5

    def test_streaming_terminal_events_do_not_duplicate_text_or_reasoning(
        self, adapter: OpenAIResponsesAdapter, provider: ProviderConfig
    ) -> None:
        _prepare(
            adapter,
            provider,
            [LLMMessage(role=Role.user, content="Hi")],
            enable_streaming=True,
        )

        chunks = [
            adapter.parse_response(
                {"type": "response.reasoning_summary_text.delta", "delta": "Think"},
                provider,
            ),
            adapter.parse_response(
                {"type": "response.output_text.delta", "delta": "Hello"},
                provider,
            ),
            adapter.parse_response(
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "type": "reasoning",
                        "summary": [{"type": "summary_text", "text": "Think"}],
                    },
                },
                provider,
            ),
            adapter.parse_response(
                {
                    "type": "response.output_item.done",
                    "output_index": 1,
                    "item": {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Hello"}],
                    },
                },
                provider,
            ),
            adapter.parse_response(
                {
                    "type": "response.completed",
                    "response": {
                        "output": [
                            {
                                "type": "reasoning",
                                "summary": [
                                    {"type": "summary_text", "text": "Think"}
                                ],
                            },
                            {
                                "type": "message",
                                "content": [
                                    {"type": "output_text", "text": "Hello"}
                                ],
                            },
                        ],
                        "usage": {"input_tokens": 3, "output_tokens": 2},
                    },
                },
                provider,
            ),
        ]

        aggregate = LLMChunk(message=LLMMessage(role=Role.assistant))
        for chunk in chunks:
            aggregate += chunk

        assert aggregate.message.reasoning_content == "Think"
        assert aggregate.message.content == "Hello"
        assert aggregate.usage is not None
        assert aggregate.usage.prompt_tokens == 3
        assert aggregate.usage.completion_tokens == 2
