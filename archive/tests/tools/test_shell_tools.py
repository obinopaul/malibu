from __future__ import annotations

from pathlib import Path
import shutil
import threading

import pytest

from tests.mock.utils import collect_result
from vibe.core.tools.base import BaseToolState, ToolError
from vibe.core.tools.builtins import (
    shell_init,
    shell_list,
    shell_run,
    shell_stop,
    shell_view,
    shell_write,
)
from vibe.core.tools.builtins._shell_sessions import (
    PersistentShellManager,
    ShellBusyError,
    ShellCommandSnapshot,
    ShellCommandTimeoutError,
    ShellSessionInfo,
    ShellSessionState,
    _choose_shell_spec,
    _Session,
    _ShellSpec,
)


class FakeShellManager:
    def __init__(self) -> None:
        self.sessions: dict[str, ShellCommandSnapshot] = {}
        self.busy = False

    def create_session(
        self, session_name: str, start_directory: str | None = None
    ) -> ShellSessionInfo:
        cwd = start_directory or str(Path.cwd())
        self.sessions[session_name] = ShellCommandSnapshot(
            session_name=session_name, shell="pwsh", cwd=cwd
        )
        return ShellSessionInfo(
            session_name=session_name,
            shell="pwsh",
            cwd=cwd,
            state=ShellSessionState.IDLE,
        )

    def list_sessions(self) -> list[ShellSessionInfo]:
        return [
            ShellSessionInfo(
                session_name=name,
                shell=snapshot.shell,
                cwd=snapshot.cwd,
                state=ShellSessionState.BUSY
                if snapshot.running
                else ShellSessionState.IDLE,
            )
            for name, snapshot in sorted(self.sessions.items())
        ]

    def run_command(
        self,
        *,
        session_name: str,
        command: str,
        run_directory: str | None,
        timeout: int,
        wait_for_output: bool,
    ) -> ShellCommandSnapshot:
        if self.busy:
            raise ShellBusyError("session is busy")
        snapshot = self.sessions[session_name]
        updated = snapshot.model_copy(
            update={
                "command": command,
                "cwd": run_directory or snapshot.cwd,
                "stdout": f"ran: {command}",
                "running": not wait_for_output,
                "returncode": None if not wait_for_output else 0,
            }
        )
        self.sessions[session_name] = updated
        return updated

    def get_session_output(self, session_name: str) -> ShellCommandSnapshot:
        return self.sessions[session_name]

    def write_to_process(
        self, session_name: str, text: str, *, press_enter: bool
    ) -> ShellCommandSnapshot:
        snapshot = self.sessions[session_name]
        updated = snapshot.model_copy(
            update={"stdout": snapshot.stdout + f"\ninput: {text}", "running": True}
        )
        self.sessions[session_name] = updated
        return updated

    def stop_current_command(
        self, session_name: str, *, kill_session: bool = False
    ) -> ShellCommandSnapshot:
        snapshot = self.sessions[session_name]
        updated = snapshot.model_copy(update={"running": False, "returncode": 130})
        if kill_session:
            self.sessions.pop(session_name, None)
        else:
            self.sessions[session_name] = updated
        return updated


class SessionTerminatingShellManager(FakeShellManager):
    def stop_current_command(
        self, session_name: str, *, kill_session: bool = False
    ) -> ShellCommandSnapshot:
        snapshot = super().stop_current_command(
            session_name, kill_session=kill_session
        )
        self.sessions.pop(session_name, None)
        return snapshot


class _FakeStdin:
    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        return


class _FakeProcess:
    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.stdout = None
        self._returncode: int | None = None

    def poll(self) -> int | None:
        return self._returncode

    def send_signal(self, signum: int) -> None:
        _ = signum

    def wait(self, timeout: float | None = None) -> int:
        _ = timeout
        self._returncode = 0
        return 0


def _patch_shell_managers(
    monkeypatch: pytest.MonkeyPatch, manager: FakeShellManager
) -> None:
    monkeypatch.setattr(shell_init, "get_shell_manager", lambda: manager)
    monkeypatch.setattr(shell_list, "get_shell_manager", lambda: manager)
    monkeypatch.setattr(shell_run, "get_shell_manager", lambda: manager)
    monkeypatch.setattr(shell_view, "get_shell_manager", lambda: manager)
    monkeypatch.setattr(shell_write, "get_shell_manager", lambda: manager)
    monkeypatch.setattr(shell_stop, "get_shell_manager", lambda: manager)


@pytest.mark.asyncio
async def test_shell_tool_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    manager = FakeShellManager()
    _patch_shell_managers(monkeypatch, manager)

    init_tool = shell_init.ShellInit(
        config=shell_init.ShellInitConfig(), state=BaseToolState()
    )
    list_tool = shell_list.ShellList(
        config=shell_list.ShellListConfig(), state=BaseToolState()
    )
    run_tool = shell_run.ShellRun(
        config=shell_run.ShellRunConfig(), state=BaseToolState()
    )
    view_tool = shell_view.ShellView(
        config=shell_view.ShellViewConfig(), state=BaseToolState()
    )
    write_tool = shell_write.ShellWrite(
        config=shell_write.ShellWriteConfig(), state=BaseToolState()
    )
    stop_tool = shell_stop.ShellStop(
        config=shell_stop.ShellStopConfig(), state=BaseToolState()
    )

    init_result = await collect_result(
        init_tool.run(shell_init.ShellInitArgs(session_name="dev"))
    )
    assert init_result.session_name == "dev"

    list_result = await collect_result(list_tool.run(shell_list.ShellListArgs()))
    assert [session.session_name for session in list_result.sessions] == ["dev"]

    run_result = await collect_result(
        run_tool.run(
            shell_run.ShellRunArgs(
                session_name="dev", command="npm run dev", wait_for_output=False
            )
        )
    )
    assert run_result.running is True

    write_result = await collect_result(
        write_tool.run(shell_write.ShellWriteArgs(session_name="dev", input="q"))
    )
    assert "input: q" in write_result.stdout

    view_result = await collect_result(
        view_tool.run(shell_view.ShellViewArgs(session_name="dev"))
    )
    assert view_result.session_name == "dev"

    stop_result = await collect_result(
        stop_tool.run(shell_stop.ShellStopArgs(session_name="dev"))
    )
    assert stop_result.running is False
    assert stop_result.session_terminated is False


@pytest.mark.asyncio
async def test_shell_run_reports_busy_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    manager = FakeShellManager()
    manager.create_session("busy")
    manager.busy = True
    _patch_shell_managers(monkeypatch, manager)

    run_tool = shell_run.ShellRun(
        config=shell_run.ShellRunConfig(), state=BaseToolState()
    )
    with pytest.raises(ToolError, match="session is busy"):
        await collect_result(
            run_tool.run(
                shell_run.ShellRunArgs(session_name="busy", command="sleep 10")
            )
        )


@pytest.mark.asyncio
async def test_shell_stop_marks_session_terminated_when_manager_removes_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    manager = SessionTerminatingShellManager()
    manager.create_session("dev")
    _patch_shell_managers(monkeypatch, manager)

    stop_tool = shell_stop.ShellStop(
        config=shell_stop.ShellStopConfig(), state=BaseToolState()
    )

    result = await collect_result(
        stop_tool.run(shell_stop.ShellStopArgs(session_name="dev"))
    )

    assert result.session_terminated is True


def test_shell_manager_timeout_clears_tracker_and_preserves_session() -> None:
    manager = PersistentShellManager()
    session = _Session(
        name="dev",
        process=_FakeProcess(),
        cwd=Path.cwd(),
        shell=_ShellSpec(argv=["pwsh"], display_name="pwsh", kind="powershell"),
        lock=threading.Lock(),
    )
    manager._sessions["dev"] = session

    def fake_interrupt_process(process: _FakeProcess) -> None:
        _ = process
        if tracker := session.tracker:
            manager._finalize_tracker(session, tracker, returncode=130)

    manager._interrupt_process = fake_interrupt_process

    with pytest.raises(ShellCommandTimeoutError, match="Partial output"):
        manager.run_command(
            session_name="dev",
            command="sleep 10",
            timeout=0.01,
            wait_for_output=True,
        )

    snapshot = manager.get_session_output("dev")

    assert snapshot.running is False
    assert snapshot.returncode == 130
    assert "[command timed out after 0.01s]" in snapshot.stdout


def test_choose_shell_spec_prefers_pwsh_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vibe.core.tools.builtins._shell_sessions.is_windows", lambda: True
    )
    monkeypatch.setattr(
        shutil,
        "which",
        lambda value: {
            "pwsh": "C:/Program Files/PowerShell/7/pwsh.exe",
            "powershell": "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
            "cmd": "C:/Windows/System32/cmd.exe",
        }.get(value),
    )

    spec = _choose_shell_spec()

    assert spec.display_name == "pwsh"


def test_choose_shell_spec_prefers_env_shell_on_posix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vibe.core.tools.builtins._shell_sessions.is_windows", lambda: False
    )
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(
        shutil,
        "which",
        lambda value: {
            "/bin/zsh": "/bin/zsh",
            "bash": "/bin/bash",
            "sh": "/bin/sh",
        }.get(value),
    )

    spec = _choose_shell_spec()

    assert spec.display_name == "zsh"
