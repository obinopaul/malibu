from __future__ import annotations

from malibu.client.client import MalibuClient
from malibu.config import get_settings


async def test_client_ext_method_awaits_async_handler(tmp_path) -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    async def handler(method: str, params: dict[str, object]) -> dict[str, object]:
        seen.append((method, params))
        return {"ok": True}

    client = MalibuClient(
        get_settings(),
        cwd=str(tmp_path),
        extension_method_handler=handler,
    )

    result = await client.ext_method("tui_interrupt", {"value": 1})

    assert result == {"ok": True}
    assert seen == [("tui_interrupt", {"value": 1})]


async def test_client_ext_notification_awaits_async_handler(tmp_path) -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    async def handler(method: str, params: dict[str, object]) -> None:
        seen.append((method, params))

    client = MalibuClient(
        get_settings(),
        cwd=str(tmp_path),
        extension_notification_handler=handler,
    )

    await client.ext_notification("tui_event", {"message": "hello"})

    assert seen == [("tui_event", {"message": "hello"})]
