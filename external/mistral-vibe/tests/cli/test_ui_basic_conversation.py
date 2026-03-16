from __future__ import annotations

import time

import pytest

from tests.conftest import build_test_agent_loop, build_test_vibe_app, build_test_vibe_config
from tests.mock.utils import mock_llm_chunk
from tests.stubs.fake_backend import FakeBackend
from vibe.cli.textual_ui.widgets.messages import AssistantMessage, UserMessage


async def _wait_until(pause, predicate, timeout: float = 5.0) -> None:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if predicate():
            return
        await pause(0.05)
    msg = "Condition was not met within the timeout."
    raise AssertionError(msg)


@pytest.mark.asyncio
async def test_ui_user_can_send_message_and_receive_response() -> None:
    config = build_test_vibe_config(
        include_project_context=False,
        include_prompt_detail=False,
        session_logging={"enabled": False},
    )
    agent_loop = build_test_agent_loop(
        config=config,
        backend=FakeBackend(mock_llm_chunk(content="Hello from the DeepAgent runtime.")),
    )
    app = build_test_vibe_app(agent_loop=agent_loop)

    async with app.run_test() as pilot:
        await pilot.press(*"Say hello")
        await pilot.press("enter")
        await _wait_until(
            pilot.pause,
            lambda: len(app.query(UserMessage)) == 1
            and len(app.query(AssistantMessage)) == 1,
        )

        user_message = app.query_one(UserMessage)
        assistant_message = app.query_one(AssistantMessage)

    assert user_message._content == "Say hello"
    assert assistant_message._content == "Hello from the DeepAgent runtime."
