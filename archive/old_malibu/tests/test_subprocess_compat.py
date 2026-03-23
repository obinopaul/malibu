from __future__ import annotations

import asyncio
import sys

import pytest

from malibu.subprocess_compat import create_subprocess_exec, spawn_stdio_transport


@pytest.mark.asyncio
async def test_create_subprocess_exec_collects_output() -> None:
    process = await create_subprocess_exec(
        sys.executable,
        "-c",
        "print('compat-ok')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()

    assert stdout is not None
    assert stderr is not None
    assert stdout.decode("utf-8").strip() == "compat-ok"
    assert stderr.decode("utf-8") == ""


@pytest.mark.asyncio
async def test_spawn_stdio_transport_round_trip() -> None:
    async with spawn_stdio_transport(
        sys.executable,
        "-c",
        (
            "import sys;"
            "data = sys.stdin.buffer.readline();"
            "sys.stdout.buffer.write(data.upper());"
            "sys.stdout.buffer.flush()"
        ),
    ) as (reader, writer, process):
        writer.write(b"ping\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)

    assert line == b"PING\n"
    assert process.returncode == 0
