from __future__ import annotations

import asyncio

from malibu.tui.app import MalibuApp


def test_malibu_app_defaults_to_malibu_cloud_theme() -> None:
    app = MalibuApp(no_welcome=True)

    assert app.theme == "malibu-cloud"


class _FakeConn:
    def __init__(self) -> None:
        self.cancel_calls: list[str] = []
        self.closed = False

    async def cancel(self, *, session_id: str) -> None:
        self.cancel_calls.append(session_id)

    async def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    async def wait(self) -> int:
        self.wait_calls += 1
        self.returncode = 0
        return 0


class _HungProcess(_FakeProcess):
    async def wait(self) -> int:
        self.wait_calls += 1
        await asyncio.sleep(0.05)
        return self.returncode or 0


async def test_malibu_app_ctrl_c_twice_quits(monkeypatch) -> None:
    app = MalibuApp(no_welcome=True)
    notifications: list[tuple[tuple[object, ...], dict[str, object]]] = []
    exited: list[bool] = []
    cancelled: list[bool] = []
    waited: list[list[object]] = []
    conn = _FakeConn()
    process = _FakeProcess()

    app._conn = conn
    app._process = process
    app.session_id = "session-1"

    monkeypatch.setattr(
        app.workers,
        "cancel_all",
        lambda: cancelled.append(True),
    )
    async def _wait_for_complete(workers: object = None) -> None:
        if workers is None:
            waited.append([])
            return
        waited.append(list(workers))

    monkeypatch.setattr(app.workers, "wait_for_complete", _wait_for_complete)

    monkeypatch.setattr(
        app,
        "notify",
        lambda *args, **kwargs: notifications.append((args, kwargs)),
    )
    monkeypatch.setattr(
        app,
        "exit",
        lambda *args, **kwargs: exited.append(True),
    )

    app.action_cancel()
    await asyncio.sleep(0)
    app.action_cancel()
    assert app._shutdown_task is not None
    await app._shutdown_task

    assert notifications
    assert conn.cancel_calls == ["session-1"]
    assert conn.closed is True
    assert cancelled == [True]
    assert waited == [[]]
    assert process.terminate_calls == 1
    assert process.kill_calls == 0
    assert process.wait_calls == 1
    assert exited == [True]


async def test_malibu_app_quit_falls_back_to_kill_on_hung_process(monkeypatch) -> None:
    app = MalibuApp(no_welcome=True)
    exited: list[bool] = []
    process = _HungProcess()

    app._conn = _FakeConn()
    app._process = process
    app.CLOSE_TIMEOUT_SECONDS = 0.01
    app.PROCESS_WAIT_TIMEOUT_SECONDS = 0.01
    app.WORKER_SHUTDOWN_TIMEOUT_SECONDS = 0.01

    monkeypatch.setattr(app.workers, "cancel_all", lambda: None)

    async def _wait_for_complete(workers: object = None) -> None:
        return None

    monkeypatch.setattr(app.workers, "wait_for_complete", _wait_for_complete)
    monkeypatch.setattr(app, "exit", lambda *args, **kwargs: exited.append(True))

    app.action_quit()
    assert app._shutdown_task is not None
    await app._shutdown_task

    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_calls >= 2
    assert exited == [True]
