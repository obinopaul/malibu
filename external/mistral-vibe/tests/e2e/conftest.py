from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
import io
import os
from pathlib import Path
import signal
from typing import cast

import pexpect
import pytest

from tests import TESTS_ROOT
from tests.e2e.common import write_e2e_config
from tests.e2e.mock_server import ChunkFactory, StreamingMockServer


@pytest.fixture
def streaming_mock_server(
    request: pytest.FixtureRequest,
) -> Iterator[StreamingMockServer]:
    chunk_factory = cast(ChunkFactory | None, getattr(request, "param", None))
    server = StreamingMockServer(chunk_factory=chunk_factory)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def setup_e2e_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    streaming_mock_server: StreamingMockServer,
) -> None:
    vibe_home = tmp_path / "vibe-home"
    write_e2e_config(vibe_home, streaming_mock_server.api_base)
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-key")
    monkeypatch.setenv("VIBE_HOME", str(vibe_home))
    monkeypatch.setenv("TERM", "xterm-256color")


@pytest.fixture
def e2e_workdir(tmp_path: Path) -> Path:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    return workdir


type SpawnedVibeContext = Iterator[tuple[pexpect.spawn, io.StringIO]]
type SpawnedVibeContextManager = AbstractContextManager[
    tuple[pexpect.spawn, io.StringIO]
]
type SpawnedVibeFactory = Callable[[Path], SpawnedVibeContextManager]


def _build_spawn(
    command: str,
    arguments: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    encoding: str,
    timeout: int,
    dimensions: tuple[int, int],
):
    spawn_cls = getattr(pexpect, "spawn", None)
    if spawn_cls is not None:
        return spawn_cls(
            command,
            arguments,
            cwd=cwd,
            env=env,
            encoding=encoding,
            timeout=timeout,
            dimensions=dimensions,
        )

    from pexpect.popen_spawn import PopenSpawn

    class WindowsPopenSpawn(PopenSpawn):
        def __init__(self, cmd: list[str], **kwargs) -> None:
            kwargs.pop("dimensions", None)
            super().__init__(cmd, **kwargs)

        def close(self, force: bool = True) -> None:
            if self.closed:
                return
            if force and self.isalive():
                self.terminate(force=True)
            self.proc.stdin.close()
            self.proc.stdout.close()
            self.closed = True

        def isalive(self) -> bool:
            return self.proc.poll() is None

        def terminate(self, force: bool = False) -> bool:
            if not self.isalive():
                return True
            self.kill(signal.SIGINT)
            try:
                self.wait()
                return True
            except Exception:
                if not force:
                    return False
            self.proc.kill()
            self.wait()
            return True

        def sendcontrol(self, char: str) -> int:
            match char.lower():
                case "c":
                    self.kill(signal.SIGINT)
                    return 1
                case _:
                    return self.send(chr(ord(char.upper()) - ord("@")))

    return WindowsPopenSpawn(
        [command, *arguments],
        cwd=cwd,
        env=env,
        encoding=encoding,
        timeout=timeout,
        dimensions=dimensions,
    )


@pytest.fixture
def spawned_vibe_process() -> SpawnedVibeFactory:
    @contextmanager
    def spawn(workdir: Path) -> SpawnedVibeContext:
        captured = io.StringIO()
        child = _build_spawn(
            "uv",
            ["run", "vibe", "--workdir", str(workdir)],
            cwd=str(TESTS_ROOT.parent),
            env=dict(os.environ),
            encoding="utf-8",
            timeout=30,
            dimensions=(36, 120),
        )
        child.logfile_read = captured

        try:
            yield child, captured
        finally:
            if child.isalive():
                child.terminate(force=True)
            if not child.closed:
                child.close()

    return spawn
