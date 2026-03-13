"""Malibu CLI entry point.

Usage
-----
::

    malibu                            — launch the terminal UI (default)
    malibu "fix the login bug"        — launch TUI with an initial prompt
    malibu --continue                 — resume the most recent session
    malibu --resume [SESSION_ID]      — resume a specific or interactively-picked session
    malibu --prompt "refactor auth"   — non-interactive single-shot mode
    malibu server                     — run as an ACP agent (stdio)
    malibu duet                       — spawn agent + client in one process (legacy)
    malibu generate-key               — generate a new API key
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Load .env into os.environ BEFORE any LangChain imports.
from dotenv import load_dotenv

load_dotenv()

# ── Version ──────────────────────────────────────────────────────

import malibu as _malibu_pkg

VERSION = _malibu_pkg.__version__


# ═══════════════════════════════════════════════════════════════════
# Argument parser
# ═══════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="malibu",
        description="Malibu — AI-powered terminal coding agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  malibu                           Start interactive terminal UI
  malibu "fix the login bug"       Start with an initial prompt
  malibu --continue                Resume the most recent session
  malibu --resume                  Pick a session to resume interactively
  malibu -p "refactor auth.py"     Non-interactive single-shot mode
  malibu server                    Run ACP agent on stdio
""",
    )

    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"Malibu v{VERSION}",
    )

    parser.add_argument(
        "--cwd", "-d",
        metavar="PATH",
        default=".",
        help="Working directory (defaults to current directory)",
    )

    parser.add_argument(
        "--prompt", "-p",
        metavar="TEXT",
        help="Execute a single prompt non-interactively and exit",
    )

    parser.add_argument(
        "--continue", "-c",
        dest="continue_session",
        action="store_true",
        help="Resume the most recent session",
    )

    parser.add_argument(
        "--resume", "-r",
        nargs="?",
        const=True,
        default=None,
        metavar="SESSION_ID",
        help="Resume a session (pick interactively if no ID given)",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging output",
    )

    parser.add_argument(
        "--no-welcome",
        action="store_true",
        help="Skip the welcome splash screen",
    )

    # Subcommands for non-TUI modes
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("server", help="Run as ACP agent on stdio")

    client_p = sub.add_parser("client", help="Connect to an agent process as client")
    client_p.add_argument("agent_cmd", nargs="+", help="Command to start the agent process")

    sub.add_parser("duet", help="Run both agent and client in one process (legacy)")

    sub.add_parser("generate-key", help="Generate a new API key for authentication")

    return parser


# ═══════════════════════════════════════════════════════════════════
# Server mode
# ═══════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════
# Client mode
# ═══════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════
# Duet mode (legacy)
# ═══════════════════════════════════════════════════════════════════

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
    src_dir = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    env["LANGSMITH_TRACING"] = "false"
    env["LANGCHAIN_TRACING_V2"] = "false"

    async with spawn_agent_process(
        client,
        sys.executable,
        "-m", "malibu", "server",
        env=env,
    ) as (conn, process):
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


# ═══════════════════════════════════════════════════════════════════
# TUI mode (DEFAULT)
# ═══════════════════════════════════════════════════════════════════

def _clear_terminal() -> None:
    """Clear the terminal screen before launching the TUI.

    Prevents shell output from bleeding into the Textual interface.
    """
    sys.stdout.write("\033[3J")   # Clear scrollback buffer
    sys.stdout.write("\033[2J")   # Clear screen
    sys.stdout.write("\033[H")    # Move cursor to home
    sys.stdout.flush()


def _run_tui(
    cwd: str,
    *,
    initial_prompt: str | None = None,
    continue_session: bool = False,
    resume_session_id: str | bool | None = None,
    no_welcome: bool = False,
) -> int:
    """Launch the Malibu terminal UI.

    Args:
        cwd: Working directory for the session.
        initial_prompt: Optional prompt to send immediately after connecting.
        continue_session: If True, resume the most recent session.
        resume_session_id: Session ID to resume, or True for interactive picker.
        no_welcome: If True, skip the welcome splash screen.

    Returns:
        Exit code.
    """
    from malibu.tui.app import MalibuApp

    _clear_terminal()

    abs_cwd = str(Path(cwd).resolve())
    app = MalibuApp(
        cwd=abs_cwd,
        initial_prompt=initial_prompt,
        continue_session=continue_session,
        resume_session_id=resume_session_id if isinstance(resume_session_id, str) else None,
        no_welcome=no_welcome,
    )
    app.run()
    return 0


# ═══════════════════════════════════════════════════════════════════
# Generate key
# ═══════════════════════════════════════════════════════════════════

def _generate_key() -> int:
    from malibu.auth.providers import APIKeyProvider

    key, hashed = APIKeyProvider.generate_key()
    print(f"API Key:  {key}")
    print(f"Hash:     {hashed}")
    print("Store the hash in your database or .env file.")
    return 0


# ═══════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════

def main() -> int:
    parser = _build_parser()

    # ── Bare prompt detection ──────────────────────────────────
    # Support: malibu "fix the bug" → launches TUI with initial prompt
    known_subcommands = {"server", "client", "duet", "generate-key"}
    argv = sys.argv[1:]
    bare_prompt: str | None = None

    has_prompt_flag = any(
        a in ("-p", "--prompt") or a.startswith("--prompt=") for a in argv
    )

    # Find first positional (non-flag) argument
    first_positional = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-p", "--prompt", "-d", "--cwd"):
            i += 2  # skip flag + value
        elif arg in ("-r", "--resume"):
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                i += 2
            else:
                i += 1
        elif arg.startswith("-"):
            i += 1
        else:
            first_positional = arg
            break

    if (
        first_positional is not None
        and first_positional not in known_subcommands
        and not has_prompt_flag
    ):
        # Separate flags from positionals → positionals become bare_prompt
        flags: list[str] = []
        prompt_parts: list[str] = []
        i = 0
        while i < len(argv):
            arg = argv[i]
            if arg in ("-p", "--prompt", "-d", "--cwd"):
                flags.extend([arg, argv[i + 1]])
                i += 2
            elif arg in ("-r", "--resume"):
                if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                    flags.extend([arg, argv[i + 1]])
                    i += 2
                else:
                    flags.append(arg)
                    i += 1
            elif arg.startswith("-"):
                flags.append(arg)
                i += 1
            else:
                prompt_parts.append(arg)
                i += 1
        bare_prompt = " ".join(prompt_parts)
        argv = flags

    args = parser.parse_args(argv)

    # ── Subcommand dispatch ────────────────────────────────────

    if args.command == "server":
        return asyncio.run(_run_server())

    elif args.command == "client":
        return asyncio.run(_run_client(args.agent_cmd, args.cwd))

    elif args.command == "duet":
        return asyncio.run(_run_duet(args.cwd))

    elif args.command == "generate-key":
        return _generate_key()

    # ── Non-interactive prompt mode ────────────────────────────

    if args.prompt:
        # Single-shot: send prompt, get response, exit
        # For now, delegates to the duet-style runner
        return asyncio.run(_run_duet(args.cwd))

    # ── Default: Launch TUI ────────────────────────────────────

    abs_cwd = str(Path(args.cwd).resolve())
    if not Path(abs_cwd).exists():
        print(f"\033[31mError: Working directory does not exist: {abs_cwd}\033[0m", file=sys.stderr)
        return 1

    return _run_tui(
        abs_cwd,
        initial_prompt=bare_prompt or args.prompt,
        continue_session=args.continue_session,
        resume_session_id=args.resume,
        no_welcome=args.no_welcome,
    )


if __name__ == "__main__":
    raise SystemExit(main())
