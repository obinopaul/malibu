"""Tests for malibu.server.extensions module."""

from __future__ import annotations

import pytest

from acp.exceptions import RequestError

from malibu.server.extensions import ExtensionRegistry


@pytest.mark.asyncio
async def test_register_and_call_method():
    reg = ExtensionRegistry()

    async def echo_handler(params):
        return {"echo": params.get("msg")}

    reg.register_method("ext/echo", echo_handler)
    result = await reg.handle_method("ext/echo", {"msg": "hello"})
    assert result == {"echo": "hello"}


@pytest.mark.asyncio
async def test_unregistered_method_raises():
    reg = ExtensionRegistry()
    with pytest.raises(RequestError):
        await reg.handle_method("ext/unknown", {})


@pytest.mark.asyncio
async def test_register_and_fire_notification():
    reg = ExtensionRegistry()
    received = []

    async def handler(params):
        received.append(params)

    reg.register_notification("ext/ping", handler)
    await reg.handle_notification("ext/ping", {"data": 1})
    assert len(received) == 1
    assert received[0]["data"] == 1


@pytest.mark.asyncio
async def test_unregistered_notification_is_noop():
    reg = ExtensionRegistry()
    # Should not raise
    await reg.handle_notification("ext/nope", {})
