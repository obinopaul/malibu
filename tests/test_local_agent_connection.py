from __future__ import annotations

import pytest
from acp import PROTOCOL_VERSION

from malibu.client.client import MalibuClient
from malibu.config import get_settings
from malibu.local_agent_connection import connect_local_agent


@pytest.mark.asyncio
async def test_connect_local_agent_can_create_session(tmp_path) -> None:
    settings = get_settings()
    client = MalibuClient(settings, cwd=str(tmp_path))

    async with connect_local_agent(client, settings=settings) as (conn, process):
        response = await conn.initialize(protocol_version=PROTOCOL_VERSION, client_capabilities=None)
        session = await conn.new_session(cwd=str(tmp_path), mcp_servers=[])

    await client.cleanup()

    assert response.protocol_version == PROTOCOL_VERSION
    assert session.session_id
    assert process.returncode == 0
