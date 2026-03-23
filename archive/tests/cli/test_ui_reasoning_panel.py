from __future__ import annotations

import asyncio
import time

import pytest

from tests.conftest import build_test_agent_loop, build_test_vibe_app, build_test_vibe_config
from tests.mock.utils import mock_llm_chunk
from tests.stubs.fake_backend import FakeBackend
from vibe.cli.textual_ui.widgets.messages import AssistantMessage, ReasoningMessage


async def _wait_until(pause, predicate, timeout: float = 5.0) -> None:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if predicate():
            return
        await pause(0.05)
    msg = "Condition was not met within the timeout."
    raise AssertionError(msg)


class DelayedFakeBackend(FakeBackend):
    def __init__(self, *args, delay: float = 0.05, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._delay = delay

    async def complete_streaming(
        self,
        *,
        model,
        messages,
        temperature,
        tools,
        tool_choice,
        extra_headers,
        max_tokens,
        metadata=None,
    ):
        async for chunk in super().complete_streaming(
            model=model,
            messages=messages,
            temperature=temperature,
            tools=tools,
            tool_choice=tool_choice,
            extra_headers=extra_headers,
            max_tokens=max_tokens,
            metadata=metadata,
        ):
            await asyncio.sleep(self._delay)
            yield chunk


@pytest.mark.asyncio
async def test_ui_streams_reasoning_in_live_panel_and_replays_to_transcript() -> None:
    config = build_test_vibe_config(
        include_project_context=False,
        include_prompt_detail=False,
        session_logging={"enabled": False},
    )
    backend = DelayedFakeBackend(
        chunks=[
            mock_llm_chunk(content="", reasoning_content="Let me think..."),
            mock_llm_chunk(content="", reasoning_content=" Carefully."),
            mock_llm_chunk(content="Here is the answer."),
        ]
    )
    agent_loop = build_test_agent_loop(
        config=config,
        backend=backend,
        enable_streaming=True,
    )
    app = build_test_vibe_app(agent_loop=agent_loop)

    async with app.run_test() as pilot:
        await pilot.press(*"Explain this")
        await pilot.press("enter")

        reasoning_panel = app.query_one("#reasoning-panel")
        reasoning_area = app.query_one("#reasoning-area")
        messages_area = app.query_one("#messages")

        await _wait_until(
            pilot.pause,
            lambda: reasoning_panel.display
            and len(list(reasoning_area.query(ReasoningMessage))) == 1,
        )

        assert len(list(messages_area.query(ReasoningMessage))) == 0
        assert len(list(messages_area.query(AssistantMessage))) == 0

        await _wait_until(
            pilot.pause,
            lambda: not reasoning_panel.display
            and len(list(messages_area.query(ReasoningMessage))) == 1
            and len(list(messages_area.query(AssistantMessage))) == 1,
        )

        transcript_reasoning = list(messages_area.query(ReasoningMessage))[0]
        transcript_assistant = list(messages_area.query(AssistantMessage))[0]

    assert transcript_reasoning.content == "Let me think... Carefully."
    assert transcript_assistant.content == "Here is the answer."
