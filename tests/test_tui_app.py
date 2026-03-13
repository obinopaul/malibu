from __future__ import annotations

from malibu.tui.app import MalibuApp


def test_malibu_app_defaults_to_malibu_cloud_theme() -> None:
    app = MalibuApp(no_welcome=True)

    assert app.theme == "malibu-cloud"


def test_malibu_app_ctrl_c_twice_quits(monkeypatch) -> None:
    app = MalibuApp(no_welcome=True)
    notifications: list[tuple[tuple[object, ...], dict[str, object]]] = []
    exited: list[bool] = []
    cancelled: list[bool] = []

    monkeypatch.setattr(
        app.workers,
        "cancel_all",
        lambda: cancelled.append(True),
    )

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
    app.action_cancel()

    assert notifications
    assert cancelled == [True]
    assert exited == [True]
