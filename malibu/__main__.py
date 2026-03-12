"""Malibu CLI entry point.

Usage:
    malibu server             — run as an ACP agent (stdio)
    malibu client <cmd> ...   — connect to an agent process as client
    malibu duet               — spawn agent subprocess + client in one process
    malibu api                — run the FastAPI HTTP/WS API
    malibu generate-key       — generate a new API key
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Load .env into os.environ BEFORE any LangChain imports.
# Pydantic Settings reads .env for Settings fields, but LangChain/LangSmith
# read os.environ directly (e.g. LANGSMITH_TRACING, LANGCHAIN_API_KEY).
from dotenv import load_dotenv

load_dotenv()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="malibu", description="Malibu ACP Agent Harness")
    sub = parser.add_subparsers(dest="command")

    # server
    sub.add_parser("server", help="Run as ACP agent on stdio")

    # client
    client_p = sub.add_parser("client", help="Spawn an agent process and connect as client")
    client_p.add_argument("agent_cmd", nargs="+", help="Command to start the agent process")
    client_p.add_argument("--cwd", default=".", help="Working directory")

    # duet
    duet_p = sub.add_parser("duet", help="Run both agent and client in one process")
    duet_p.add_argument("--cwd", default=".", help="Working directory")

    # api
    api_p = sub.add_parser("api", help="Run FastAPI HTTP/WS server")
    api_p.add_argument("--host", default="0.0.0.0", help="Bind host")
    api_p.add_argument("--port", type=int, default=8000, help="Bind port")

    # generate-key
    sub.add_parser("generate-key", help="Generate a new API key for authentication")

    return parser


# ─── Server mode ──────────────────────────────────────────────

async def _run_server() -> int:
    from acp import run_agent

    from malibu.config import get_settings
    from malibu.server.agent import MalibuAgent
    from malibu.telemetry.logging import setup_logging

    settings = get_settings()
    setup_logging(settings)

    agent = MalibuAgent(settings)
    await run_agent(agent)
    return 0


# ─── Client mode ──────────────────────────────────────────────

async def _run_client(agent_cmd: list[str], cwd: str) -> int:
    from acp import PROTOCOL_VERSION, spawn_agent_process

    from malibu.client.client import MalibuClient
    from malibu.config import get_settings
    from malibu.telemetry.logging import setup_logging

    settings = get_settings()
    setup_logging(settings)

    abs_cwd = str(Path(cwd).resolve())
    client = MalibuClient(settings, cwd=abs_cwd)

    env = os.environ.copy()

    async with spawn_agent_process(client, agent_cmd[0], *agent_cmd[1:], env=env) as (conn, process):
        await conn.initialize(protocol_version=PROTOCOL_VERSION, client_capabilities=None)
        session = await conn.new_session(mcp_servers=[], cwd=abs_cwd)
        await _interactive_loop(conn, session.session_id)

    await client.cleanup()
    return process.returncode or 0


async def _interactive_loop(conn, session_id: str) -> None:
    """Simple REPL for interacting with the agent."""
    from acp import text_block

    print("\nMalibu Client — type a message (Ctrl+C to quit)\n")
    loop = asyncio.get_running_loop()
    while True:
        try:
            user_input = await loop.run_in_executor(None, lambda: input("> "))
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        try:
            response = await conn.prompt(session_id=session_id, prompt=[text_block(user_input)])
        except Exception as exc:
            print(f"\033[31mError: {exc}\033[0m")
            continue
        # Print a newline after streamed output
        print()


async def _drain_stderr(process: asyncio.subprocess.Process) -> None:
    """Read subprocess stderr and print lines prefixed with [agent]."""
    if process.stderr is None:
        return
    try:
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            print(f"\033[90m[agent] {line.decode(errors='replace').rstrip()}\033[0m", file=sys.stderr)
    except asyncio.CancelledError:
        pass


# ─── Duet mode ────────────────────────────────────────────────

async def _run_duet(cwd: str) -> int:
    from acp import PROTOCOL_VERSION, spawn_agent_process

    from malibu.client.client import MalibuClient
    from malibu.config import get_settings
    from malibu.telemetry.logging import setup_logging

    settings = get_settings()
    setup_logging(settings)

    abs_cwd = str(Path(cwd).resolve())
    client = MalibuClient(settings, cwd=abs_cwd)

    env = os.environ.copy()
    # Ensure the malibu package is importable by the subprocess
    src_dir = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    # Disable tracing in subprocess to prevent hangs when LangSmith
    # API key is missing or the tracing server is unreachable.
    env["LANGSMITH_TRACING"] = "false"
    env["LANGCHAIN_TRACING_V2"] = "false"

    async with spawn_agent_process(
        client,
        sys.executable,
        "-m", "malibu", "server",
        env=env,
    ) as (conn, process):
        # Monitor subprocess stderr so crashes are visible
        stderr_task = asyncio.create_task(_drain_stderr(process))
        try:
            await asyncio.wait_for(
                conn.initialize(protocol_version=PROTOCOL_VERSION, client_capabilities=None),
                timeout=15.0,
            )
            session = await asyncio.wait_for(
                conn.new_session(mcp_servers=[], cwd=abs_cwd),
                timeout=15.0,
            )
            await _interactive_loop(conn, session.session_id)
        finally:
            stderr_task.cancel()

    await client.cleanup()
    return process.returncode or 0


# ─── API mode ─────────────────────────────────────────────────

def _run_api(host: str, port: int) -> int:
    import uvicorn

    from malibu.config import get_settings
    from malibu.telemetry.logging import setup_logging

    settings = get_settings()
    setup_logging(settings)

    uvicorn.run("malibu.api.app:create_app", host=host, port=port, factory=True, log_level="info")
    return 0


# ─── Generate key ─────────────────────────────────────────────

def _generate_key() -> int:
    from malibu.auth.providers import APIKeyProvider

    key, hashed = APIKeyProvider.generate_key()
    print(f"API Key:  {key}")
    print(f"Hash:     {hashed}")
    print("Store the hash in your database or .env file.")
    return 0


# ─── main ─────────────────────────────────────────────────────

def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "server":
        return asyncio.run(_run_server())
    elif args.command == "client":
        return asyncio.run(_run_client(args.agent_cmd, args.cwd))
    elif args.command == "duet":
        return asyncio.run(_run_duet(args.cwd))
    elif args.command == "api":
        return _run_api(args.host, args.port)
    elif args.command == "generate-key":
        return _generate_key()
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
