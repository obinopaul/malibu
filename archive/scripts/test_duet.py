"""End-to-end duet test — spawns an agent subprocess and runs prompts against it.

This is the real user flow: spawn_agent_process over stdio, initialize,
create session, send prompts, and see streaming output.
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure malibu package is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env into os.environ BEFORE LangChain imports so LANGSMITH_TRACING is seen.
from dotenv import load_dotenv

load_dotenv()


async def main():
    from acp import PROTOCOL_VERSION, spawn_agent_process, text_block

    from malibu.client.client import MalibuClient
    from malibu.config import get_settings
    from malibu.telemetry.logging import setup_logging

    settings = get_settings()
    setup_logging(settings)

    abs_cwd = str(Path(".").resolve())
    client = MalibuClient(settings, cwd=abs_cwd)

    env = os.environ.copy()
    src_dir = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    env["LANGSMITH_TRACING"] = "false"
    env["LANGCHAIN_TRACING_V2"] = "false"

    print("=" * 60)
    print("MALIBU DUET END-TO-END TEST")
    print("=" * 60)
    print(f"Working directory: {abs_cwd}")
    print(f"Agent command: {sys.executable} -m malibu server")
    print()

    async with spawn_agent_process(
        client,
        sys.executable,
        "-m", "malibu", "server",
        env=env,
    ) as (conn, process):
        # 1. Initialize
        print("--- INITIALIZE ---")
        init_resp = await conn.initialize(
            protocol_version=PROTOCOL_VERSION,
            client_capabilities=None,
        )
        print(f"Protocol version: {init_resp.protocol_version}")
        print()

        # 2. New session
        print("--- NEW SESSION ---")
        session = await conn.new_session(mcp_servers=[], cwd=abs_cwd)
        sid = session.session_id
        print(f"Session: {sid}")
        print()

        # 3. Simple prompt
        print("--- PROMPT: 'What is 2+2? Answer briefly.' ---")
        resp1 = await conn.prompt(session_id=sid, prompt=[text_block("What is 2+2? Answer briefly.")])
        print(f"\nStop reason: {resp1.stop_reason}")
        print()

        # 4. Tool prompt
        print("--- PROMPT: 'List files in this directory using the ls tool.' ---")
        resp2 = await conn.prompt(session_id=sid, prompt=[text_block("List files in this directory using the ls tool.")])
        print(f"\nStop reason: {resp2.stop_reason}")
        print()

        # 5. Multi-turn conversation
        print("--- PROMPT: 'What was my first question?' ---")
        resp3 = await conn.prompt(session_id=sid, prompt=[text_block("What was my first question?")])
        print(f"\nStop reason: {resp3.stop_reason}")
        print()

    print("=" * 60)
    print("ALL DUET TESTS PASSED")
    print("=" * 60)
    await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
