from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import threading
import time
import uuid

from pydantic import BaseModel

from vibe.core.tools.base import ToolError
from vibe.core.tools.builtins._file_tool_utils import (
    ensure_existing_directory,
    resolve_tool_path,
)
from vibe.core.tools.builtins.bash import _get_base_env, _get_subprocess_encoding
from vibe.core.utils import is_windows

_DONE_PREFIX = "__VIBE_SHELL_DONE__"
_POLL_INTERVAL_SECONDS = 0.1
_MAX_BUFFER_LINES = 2000
_STARTUP_TIMEOUT_SECONDS = 5
_INTERRUPT_WAIT_SECONDS = 5
_TIMEOUT_RETURN_CODE = 124
_INTERRUPTED_RETURN_CODE = 130


class ShellSessionState(StrEnum):
    IDLE = auto()
    BUSY = auto()


class ShellSessionError(ToolError):
    pass


class ShellBusyError(ShellSessionError):
    pass


class ShellSessionNotFoundError(ShellSessionError):
    pass


class ShellSessionExistsError(ShellSessionError):
    pass


class ShellCommandTimeoutError(ShellSessionError):
    pass


class ShellCommandSnapshot(BaseModel):
    session_name: str
    shell: str
    cwd: str
    command: str | None = None
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    running: bool = False


class ShellSessionInfo(BaseModel):
    session_name: str
    shell: str
    cwd: str
    state: ShellSessionState


@dataclass(slots=True, frozen=True)
class _ShellSpec:
    argv: list[str]
    display_name: str
    kind: str


@dataclass(slots=True)
class _CommandTracker:
    token: str
    command: str
    start_index: int
    event: threading.Event = field(default_factory=threading.Event)
    returncode: int | None = None


@dataclass(slots=True)
class _Session:
    name: str
    process: subprocess.Popen[str]
    cwd: Path
    shell: _ShellSpec
    output_lines: list[str] = field(default_factory=list)
    tracker: _CommandTracker | None = None
    last_command: str | None = None
    last_returncode: int | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    reader: threading.Thread | None = None

    def append_output(self, text: str) -> None:
        with self.lock:
            self.output_lines.append(text.rstrip("\r\n"))
            if len(self.output_lines) > _MAX_BUFFER_LINES:
                self.output_lines = self.output_lines[-_MAX_BUFFER_LINES:]

    def get_output_from(self, start_index: int = 0) -> str:
        with self.lock:
            return "\n".join(self.output_lines[start_index:]).strip()


class PersistentShellManager:
    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def list_sessions(self) -> list[ShellSessionInfo]:
        self._prune_dead_sessions()
        return [
            ShellSessionInfo(
                session_name=session.name,
                shell=session.shell.display_name,
                cwd=str(session.cwd),
                state=self._get_state(session),
            )
            for session in sorted(self._sessions.values(), key=lambda item: item.name)
        ]

    def create_session(
        self, session_name: str, start_directory: str | None = None
    ) -> ShellSessionInfo:
        self._validate_session_name(session_name)
        cwd = ensure_existing_directory(
            resolve_tool_path(start_directory or str(Path.cwd()))
        )
        shell_spec = _choose_shell_spec()
        process = self._spawn_process(shell_spec, cwd)
        session = _Session(name=session_name, process=process, cwd=cwd, shell=shell_spec)
        session.reader = threading.Thread(
            target=self._reader_loop,
            args=(session,),
            daemon=True,
            name=f"vibe-shell-{session_name}",
        )
        session.reader.start()

        with self._lock:
            self._prune_dead_sessions()
            if session_name in self._sessions:
                self._terminate_process(process)
                raise ShellSessionExistsError(f"Session '{session_name}' already exists")
            self._sessions[session_name] = session

        try:
            self._wait_for_startup(session)
        except Exception:
            self._terminate_process(process)
            with self._lock:
                self._sessions.pop(session_name, None)
            raise

        return ShellSessionInfo(
            session_name=session.name,
            shell=session.shell.display_name,
            cwd=str(session.cwd),
            state=ShellSessionState.IDLE,
        )

    def delete_session(self, session_name: str) -> None:
        session = self._require_session(session_name)
        self._terminate_process(session.process)
        with self._lock:
            self._sessions.pop(session_name, None)

    def run_command(
        self,
        *,
        session_name: str,
        command: str,
        run_directory: str | None = None,
        timeout: int,
        wait_for_output: bool,
    ) -> ShellCommandSnapshot:
        session = self._require_session(session_name)
        if not command.strip():
            raise ShellSessionError("Command cannot be empty")

        if run_directory is not None:
            session.cwd = ensure_existing_directory(resolve_tool_path(run_directory))

        tracker = self._begin_command(session, command=command, record_command=True)
        try:
            self._write(session, self._build_payload(session, command, tracker.token))
        except Exception:
            self._finalize_tracker(session, tracker, returncode=None)
            raise

        if not wait_for_output:
            time.sleep(_POLL_INTERVAL_SECONDS)
            return self._build_snapshot(session, tracker=tracker, running=True)

        if tracker.event.wait(timeout=timeout):
            return self._build_snapshot(
                session,
                tracker=tracker,
                running=False,
                returncode=tracker.returncode,
            )

        self._interrupt_process(session.process)
        if tracker.event.wait(timeout=_INTERRUPT_WAIT_SECONDS):
            session.append_output(f"[command timed out after {timeout}s]")
            resolved_returncode = (
                tracker.returncode
                if tracker.returncode is not None
                else _TIMEOUT_RETURN_CODE
            )
            snapshot = self._build_snapshot(
                session,
                tracker=tracker,
                running=False,
                returncode=resolved_returncode,
            )
        else:
            snapshot = self._terminate_unresponsive_session(
                session_name,
                session,
                tracker,
                returncode=_TIMEOUT_RETURN_CODE,
                note=f"[command timed out after {timeout}s; session terminated]",
            )

        detail = f"Command timed out after {timeout}s in session '{session_name}'"
        if session_name not in self._sessions:
            detail += "; the session was terminated because it did not stop cleanly"
        if snapshot.stdout:
            detail += f"\nPartial output:\n{snapshot.stdout}"
        raise ShellCommandTimeoutError(detail)

    def get_session_output(self, session_name: str) -> ShellCommandSnapshot:
        session = self._require_session(session_name)
        with session.lock:
            tracker = session.tracker
            last_returncode = session.last_returncode
        return self._build_snapshot(
            session,
            tracker=tracker,
            running=tracker is not None,
            returncode=tracker.returncode if tracker else last_returncode,
            full_buffer=True,
        )

    def write_to_process(
        self, session_name: str, text: str, *, press_enter: bool
    ) -> ShellCommandSnapshot:
        if not text:
            raise ShellSessionError("Input cannot be empty")

        session = self._require_session(session_name)
        payload = text + ("\n" if press_enter else "")
        self._write(session, payload)
        time.sleep(_POLL_INTERVAL_SECONDS)
        return self.get_session_output(session_name)

    def stop_current_command(
        self, session_name: str, *, kill_session: bool = False
    ) -> ShellCommandSnapshot:
        session = self._require_session(session_name)
        if kill_session:
            snapshot = self.get_session_output(session_name)
            self.delete_session(session_name)
            return snapshot

        with session.lock:
            tracker = session.tracker

        if tracker is None:
            return self.get_session_output(session_name)

        self._interrupt_process(session.process)
        if tracker.event.wait(timeout=_INTERRUPT_WAIT_SECONDS):
            session.append_output("[command interrupted]")
            return self.get_session_output(session_name)

        return self._terminate_unresponsive_session(
            session_name,
            session,
            tracker,
            returncode=_INTERRUPTED_RETURN_CODE,
            note="[command interrupted; session terminated]",
        )

    def _begin_command(
        self, session: _Session, *, command: str, record_command: bool
    ) -> _CommandTracker:
        with session.lock:
            if session.tracker is not None:
                raise ShellBusyError(
                    f"Session '{session.name}' is busy with command '{session.tracker.command}'"
                )
            tracker = _CommandTracker(
                token=uuid.uuid4().hex,
                command=command,
                start_index=len(session.output_lines),
            )
            session.tracker = tracker
            if record_command:
                session.last_command = command
        return tracker

    def _finalize_tracker(
        self, session: _Session, tracker: _CommandTracker, *, returncode: int | None
    ) -> None:
        with session.lock:
            if session.tracker is not tracker:
                return
            tracker.returncode = returncode
            session.last_returncode = returncode
            session.tracker = None
            tracker.event.set()

    def _terminate_unresponsive_session(
        self,
        session_name: str,
        session: _Session,
        tracker: _CommandTracker,
        *,
        returncode: int,
        note: str,
    ) -> ShellCommandSnapshot:
        self._finalize_tracker(session, tracker, returncode=returncode)
        session.append_output(note)
        snapshot = self._build_snapshot(
            session,
            tracker=tracker,
            running=False,
            returncode=returncode,
        )
        self._terminate_process(session.process)
        with self._lock:
            self._sessions.pop(session_name, None)
        return snapshot

    def _build_snapshot(
        self,
        session: _Session,
        *,
        tracker: _CommandTracker | None,
        running: bool,
        returncode: int | None = None,
        full_buffer: bool = False,
    ) -> ShellCommandSnapshot:
        output = (
            session.get_output_from(0)
            if full_buffer or tracker is None
            else session.get_output_from(tracker.start_index)
        )
        return ShellCommandSnapshot(
            session_name=session.name,
            shell=session.shell.display_name,
            cwd=str(session.cwd),
            command=tracker.command if tracker else session.last_command,
            stdout=output,
            stderr="",
            returncode=returncode,
            running=running,
        )

    def _reader_loop(self, session: _Session) -> None:
        stdout = session.process.stdout
        if stdout is None:
            return

        for raw_line in iter(stdout.readline, ""):
            if not raw_line:
                break
            stripped = raw_line.strip()
            if stripped.startswith(_DONE_PREFIX):
                token, _, exit_code_text = stripped.partition(":")
                token = token.removeprefix(_DONE_PREFIX)
                with session.lock:
                    tracker = session.tracker
                    if tracker and tracker.token == token:
                        tracker.returncode = _parse_exit_code(exit_code_text)
                        session.last_returncode = tracker.returncode
                        session.tracker = None
                        tracker.event.set()
                continue

            session.append_output(raw_line)

        with session.lock:
            tracker = session.tracker
            session.tracker = None
        if tracker is not None:
            tracker.returncode = session.process.poll()
            with session.lock:
                session.last_returncode = tracker.returncode
            tracker.event.set()

    def _spawn_process(
        self, shell_spec: _ShellSpec, cwd: Path
    ) -> subprocess.Popen[str]:
        kwargs: dict[str, object] = {
            "cwd": str(cwd),
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": _get_subprocess_encoding(),
            "errors": "replace",
            "bufsize": 1,
            "env": _build_shell_env(),
        }

        if is_windows():
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        return subprocess.Popen(shell_spec.argv, **kwargs)

    def _build_payload(self, session: _Session, command: str, token: str) -> str:
        lines: list[str] = [self._build_cd_command(session)]
        lines.append(command)
        match session.shell.kind:
            case "powershell":
                lines.append(
                    "$__vibeExit = if ($LASTEXITCODE -ne $null) { [int]$LASTEXITCODE } "
                    "elseif ($?) { 0 } else { 1 }"
                )
                lines.append(f'Write-Output "{_DONE_PREFIX}{token}:$($__vibeExit)"')
            case "cmd":
                lines.append(f"echo {_DONE_PREFIX}{token}:%errorlevel%")
            case _:
                lines.append(f'printf "{_DONE_PREFIX}{token}:%s\\n" "$?"')
        return "\n".join(lines) + "\n"

    def _build_cd_command(self, session: _Session) -> str:
        match session.shell.kind:
            case "powershell":
                escaped = str(session.cwd).replace("'", "''")
                return f"Set-Location -LiteralPath '{escaped}'"
            case "cmd":
                return f'cd /d "{session.cwd}"'
            case _:
                return f"cd {shlex.quote(str(session.cwd))}"

    def _write(self, session: _Session, payload: str) -> None:
        stdin = session.process.stdin
        if stdin is None or session.process.poll() is not None:
            raise ShellSessionError(f"Session '{session.name}' is not available")

        try:
            stdin.write(payload)
            stdin.flush()
        except OSError as exc:
            raise ShellSessionError(
                f"Failed to write to session '{session.name}': {exc}"
            ) from exc

    def _interrupt_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if is_windows():
            process.send_signal(signal.CTRL_BREAK_EVENT)
            return
        os.killpg(os.getpgid(process.pid), signal.SIGINT)

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return

        if is_windows():
            process.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                process.wait(timeout=2)
                return
            except subprocess.TimeoutExpired:
                process.terminate()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            try:
                process.wait(timeout=2)
                return
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)

        process.wait(timeout=5)

    def _wait_for_startup(self, session: _Session) -> None:
        tracker = self._begin_command(
            session,
            command=_startup_command(session.shell),
            record_command=False,
        )
        try:
            self._write(
                session, self._build_payload(session, tracker.command, tracker.token)
            )
            if not tracker.event.wait(timeout=_STARTUP_TIMEOUT_SECONDS):
                raise ShellSessionError("Shell session startup timed out")
            if session.process.poll() is not None:
                raise ShellSessionError("Shell session exited during startup")
            if tracker.returncode not in {None, 0}:
                raise ShellSessionError("Shell session failed its startup probe")
        except Exception:
            self._finalize_tracker(session, tracker, returncode=tracker.returncode)
            raise

    def _require_session(self, session_name: str) -> _Session:
        self._prune_dead_sessions()
        session = self._sessions.get(session_name)
        if session is None:
            raise ShellSessionNotFoundError(f"Session '{session_name}' was not found")
        return session

    def _prune_dead_sessions(self) -> None:
        dead = [
            name
            for name, session in self._sessions.items()
            if session.process.poll() is not None
        ]
        for name in dead:
            self._sessions.pop(name, None)

    def _get_state(self, session: _Session) -> ShellSessionState:
        return (
            ShellSessionState.BUSY
            if session.tracker is not None
            else ShellSessionState.IDLE
        )

    def _validate_session_name(self, session_name: str) -> None:
        if (
            not session_name
            or not session_name.replace("-", "").replace("_", "").isalnum()
        ):
            raise ShellSessionError(
                "Invalid session name. Use only letters, numbers, hyphens, and underscores."
            )


def _build_shell_env() -> dict[str, str]:
    env = _get_base_env()
    env["PS1"] = ""
    env.setdefault("PROMPT", "$P$G")
    return env


def _startup_command(shell_spec: _ShellSpec) -> str:
    match shell_spec.kind:
        case "powershell":
            return "$null = $PSVersionTable.PSVersion"
        case "cmd":
            return "ver >nul"
        case _:
            return ":"


def _parse_exit_code(exit_code_text: str) -> int | None:
    try:
        return int(exit_code_text)
    except ValueError:
        return None


def _choose_shell_spec() -> _ShellSpec:
    if is_windows():
        if pwsh := shutil.which("pwsh"):
            return _ShellSpec(
                argv=[pwsh, "-NoLogo", "-NoProfile", "-Command", "-"],
                display_name="pwsh",
                kind="powershell",
            )
        if powershell := shutil.which("powershell"):
            return _ShellSpec(
                argv=[powershell, "-NoLogo", "-NoProfile", "-Command", "-"],
                display_name="powershell",
                kind="powershell",
            )
        if cmd := shutil.which("cmd"):
            return _ShellSpec(argv=[cmd, "/Q", "/K"], display_name="cmd", kind="cmd")
        raise ShellSessionError(
            "No supported shell was found. Install pwsh, powershell, or cmd."
        )

    candidates = [os.environ.get("SHELL"), shutil.which("bash"), shutil.which("sh")]
    for candidate in candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if candidate_path.exists() or shutil.which(candidate):
            return _ShellSpec(
                argv=[str(candidate)],
                display_name=Path(candidate).name,
                kind="posix",
            )

    raise ShellSessionError("No supported shell was found. Install bash or sh.")


_SHELL_MANAGER: PersistentShellManager | None = None


def get_shell_manager() -> PersistentShellManager:
    global _SHELL_MANAGER
    if _SHELL_MANAGER is None:
        _SHELL_MANAGER = PersistentShellManager()
    return _SHELL_MANAGER
