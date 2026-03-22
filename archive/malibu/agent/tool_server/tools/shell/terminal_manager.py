from __future__ import annotations

import os
import platform
import shlex
import signal
import subprocess
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List

from pydantic import BaseModel

_DEFAULT_TIMEOUT = 60
_MAX_TIMEOUT = 180
_POLL_INTERVAL = 0.1
_DONE_PREFIX = "__MALIBU_CMD_DONE__"
_MAX_BUFFER_LINES = 2000


class ShellResult(BaseModel):
    clean_output: str
    ansi_output: str


class ShellError(Exception):
    pass


class ShellBusyError(ShellError):
    pass


class ShellInvalidSessionNameError(ShellError):
    pass


class ShellSessionNotFoundError(ShellError):
    pass


class ShellSessionExistsError(ShellError):
    pass


class ShellRunDirNotFoundError(ShellError):
    pass


class ShellCommandTimeoutError(ShellError):
    pass


class ShellOperationError(ShellError):
    pass


TmuxSessionExists = ShellSessionExistsError


class SessionState(Enum):
    BUSY = "busy"
    IDLE = "idle"


class BaseShellManager(ABC):
    @abstractmethod
    def get_all_sessions(self) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def create_session(
        self, session_name: str, base_dir: str, timeout: int = _DEFAULT_TIMEOUT
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_session(self, session_name: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def run_command(
        self,
        session_name: str,
        command: str,
        run_dir: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        wait_for_output: bool = True,
    ) -> ShellResult:
        raise NotImplementedError

    @abstractmethod
    def kill_current_command(
        self, session_name: str, timeout: int = _DEFAULT_TIMEOUT
    ) -> ShellResult:
        raise NotImplementedError

    @abstractmethod
    def get_session_state(self, session_name: str) -> SessionState:
        raise NotImplementedError

    @abstractmethod
    def get_session_output(self, session_name: str) -> ShellResult:
        raise NotImplementedError

    @abstractmethod
    def write_to_process(
        self, session_name: str, input: str, press_enter: bool
    ) -> ShellResult:
        raise NotImplementedError


@dataclass
class _CommandTracker:
    token: str
    event: threading.Event = field(default_factory=threading.Event)
    exit_code: int | None = None


@dataclass
class _ShellSession:
    name: str
    process: subprocess.Popen[str]
    cwd: str
    lock: threading.Lock = field(default_factory=threading.Lock)
    output_lines: list[str] = field(default_factory=list)
    tracker: _CommandTracker | None = None
    reader: threading.Thread | None = None

    def append_output(self, line: str) -> None:
        with self.lock:
            self.output_lines.append(line.rstrip("\r\n"))
            if len(self.output_lines) > _MAX_BUFFER_LINES:
                self.output_lines = self.output_lines[-_MAX_BUFFER_LINES:]

    def current_output(self) -> ShellResult:
        with self.lock:
            text = "\n".join(self.output_lines).strip()
        return ShellResult(clean_output=text, ansi_output=text)


class LocalShellSessionManager(BaseShellManager):
    """Cross-platform persistent shell session manager."""

    def __init__(self) -> None:
        self._sessions: dict[str, _ShellSession] = {}
        self._is_windows = platform.system() == "Windows"

    def get_all_sessions(self) -> List[str]:
        self._prune_dead_sessions()
        return sorted(self._sessions.keys())

    def create_session(
        self, session_name: str, start_directory: str, timeout: int = _DEFAULT_TIMEOUT
    ) -> None:
        self._validate_session_name(session_name)
        start_directory = self._validate_directory(start_directory)
        if session_name in self._sessions:
            raise ShellSessionExistsError(f"Session '{session_name}' already exists")

        process = self._spawn_process(start_directory)
        session = _ShellSession(
            name=session_name,
            process=process,
            cwd=start_directory,
        )
        session.reader = threading.Thread(
            target=self._reader_loop,
            args=(session,),
            daemon=True,
            name=f"shell-reader-{session_name}",
        )
        session.reader.start()
        self._sessions[session_name] = session
        self._wait_for_shell_ready(timeout=timeout)

    def delete_session(self, session_name: str) -> None:
        session = self._require_session(session_name)
        self._terminate_process(session.process)
        self._sessions.pop(session_name, None)

    def run_command(
        self,
        session_name: str,
        command: str,
        run_dir: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        wait_for_output: bool = True,
    ) -> ShellResult:
        session = self._require_session(session_name)
        if self.get_session_state(session_name) == SessionState.BUSY:
            raise ShellBusyError("Session is busy, the last command is not finished.")

        if run_dir:
            run_dir = self._validate_directory(run_dir)
            session.cwd = run_dir

        tracker = _CommandTracker(token=uuid.uuid4().hex)
        with session.lock:
            session.tracker = tracker

        payload = self._build_command_payload(command, tracker.token, run_dir)
        self._write(session, payload)

        if wait_for_output:
            finished = tracker.event.wait(timeout=min(timeout, _MAX_TIMEOUT))
            if not finished:
                raise ShellCommandTimeoutError("Command timed out")

        return session.current_output()

    def kill_current_command(
        self, session_name: str, timeout: int = _DEFAULT_TIMEOUT
    ) -> ShellResult:
        session = self._require_session(session_name)
        tracker = session.tracker
        if tracker is None:
            return session.current_output()

        self._interrupt_process(session.process)
        finished = tracker.event.wait(timeout=min(timeout, 5))
        if not finished:
            interrupted_line = None
            with session.lock:
                if session.tracker is tracker:
                    interrupted_line = "[command interrupted]"
                    tracker.exit_code = 130
                    tracker.event.set()
                    session.tracker = None
            if interrupted_line is not None:
                session.append_output(interrupted_line)
        return session.current_output()

    def get_session_state(self, session_name: str) -> SessionState:
        session = self._require_session(session_name)
        if session.process.poll() is not None:
            return SessionState.IDLE
        return SessionState.BUSY if session.tracker is not None else SessionState.IDLE

    def get_session_output(self, session_name: str) -> ShellResult:
        session = self._require_session(session_name)
        return session.current_output()

    def write_to_process(
        self, session_name: str, input: str, press_enter: bool
    ) -> ShellResult:
        session = self._require_session(session_name)
        payload = input + ("\n" if press_enter else "")
        self._write(session, payload)
        time.sleep(0.1)
        return session.current_output()

    def _prune_dead_sessions(self) -> None:
        dead = [
            name
            for name, session in self._sessions.items()
            if session.process.poll() is not None
        ]
        for name in dead:
            self._sessions.pop(name, None)

    def _require_session(self, session_name: str) -> _ShellSession:
        self._prune_dead_sessions()
        session = self._sessions.get(session_name)
        if session is None:
            raise ShellSessionNotFoundError(f"Session '{session_name}' not found")
        return session

    def _validate_session_name(self, session_name: str) -> None:
        if not session_name or not session_name.replace("_", "").replace("-", "").isalnum():
            raise ShellInvalidSessionNameError(
                "Invalid session name. Only alphanumeric characters, hyphens, and underscores are allowed."
            )

    def _validate_directory(self, directory: str) -> str:
        if not directory.strip():
            raise ShellRunDirNotFoundError("Directory path cannot be empty")

        try:
            path = Path(directory).resolve()
            if not path.exists():
                raise ShellRunDirNotFoundError(f"Directory does not exist: {directory}")
            if not path.is_dir():
                raise ShellRunDirNotFoundError(f"Path is not a directory: {directory}")
            return str(path)
        except (OSError, RuntimeError) as exc:
            raise ShellRunDirNotFoundError(f"Invalid directory path: {exc}") from exc

    def _spawn_process(self, cwd: str) -> subprocess.Popen[str]:
        kwargs: dict[str, object] = {
            "cwd": cwd,
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
            "env": {**os.environ, "TERM": os.environ.get("TERM", "xterm-256color")},
        }

        if self._is_windows:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            return subprocess.Popen(
                ["pwsh", "-NoLogo", "-NoProfile", "-NoExit"],
                **kwargs,
            )

        kwargs["preexec_fn"] = os.setsid
        return subprocess.Popen(
            ["/bin/bash", "-l"],
            **kwargs,
        )

    def _reader_loop(self, session: _ShellSession) -> None:
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
                        try:
                            tracker.exit_code = int(exit_code_text)
                        except ValueError:
                            tracker.exit_code = None
                        tracker.event.set()
                        session.tracker = None
                continue
            session.append_output(raw_line)

        with session.lock:
            tracker = session.tracker
            session.tracker = None
        if tracker:
            tracker.exit_code = session.process.poll()
            tracker.event.set()

    def _build_command_payload(
        self, command: str, token: str, run_dir: str | None
    ) -> str:
        lines: list[str] = []
        if run_dir:
            lines.append(self._build_cd_command(run_dir))

        lines.append(command)

        if self._is_windows:
            lines.append(
                "$__malibuExit = if ($LASTEXITCODE -ne $null) { [int]$LASTEXITCODE } "
                "elseif ($?) { 0 } else { 1 }"
            )
            lines.append(f'Write-Output "{_DONE_PREFIX}{token}:$($__malibuExit)"')
        else:
            lines.append(f'printf "{_DONE_PREFIX}{token}:%s\\n" "$?"')

        return "\n".join(lines) + "\n"

    def _build_cd_command(self, run_dir: str) -> str:
        if self._is_windows:
            escaped = run_dir.replace("'", "''")
            return f"Set-Location -LiteralPath '{escaped}'"
        return f"cd {shlex.quote(run_dir)}"

    def _write(self, session: _ShellSession, payload: str) -> None:
        stdin = session.process.stdin
        if stdin is None or session.process.poll() is not None:
            raise ShellOperationError(
                f"Session '{session.name}' is not available for input"
            )
        try:
            stdin.write(payload)
            stdin.flush()
        except OSError as exc:
            raise ShellOperationError(
                f"Failed to write to session '{session.name}': {exc}"
            ) from exc

    def _interrupt_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if self._is_windows:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGINT)

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if self._is_windows:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                process.wait(timeout=2)
                return
            except subprocess.TimeoutExpired:
                process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
                return
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)

    def _wait_for_shell_ready(self, timeout: int) -> None:
        end = time.time() + min(timeout, _MAX_TIMEOUT)
        while time.time() < end:
            time.sleep(_POLL_INTERVAL)
            return
        raise ShellCommandTimeoutError("Session creation timed out")

