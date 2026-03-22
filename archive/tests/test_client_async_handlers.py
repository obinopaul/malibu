from __future__ import annotations

from acp.schema import AgentMessageChunk, TextContentBlock

from malibu.client.client import MalibuClient
from malibu.config import get_settings


async def test_session_update_awaits_async_display_handler(tmp_path) -> None:
    seen: list[str] = []

    async def display_handler(session_id: str, update: object, **kwargs: object) -> None:
        seen.append(f"{session_id}:{type(update).__name__}")

    client = MalibuClient(
        get_settings(),
        cwd=str(tmp_path),
        display_handler=display_handler,
    )

    await client.session_update(
        "sess-1",
        AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text="hello"),
        ),
    )

    assert seen == ["sess-1:AgentMessageChunk"]
