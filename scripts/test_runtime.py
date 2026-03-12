"""Runtime smoke test — verify the full Malibu prompt flow works end-to-end.

Tests:
  1. Agent instantiation + initialize
  2. Session creation + agent graph build
  3. Single prompt with real LLM → streaming response
  4. Tool call flow (ls tool)
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Ensure malibu package is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env into os.environ BEFORE LangChain imports so LANGSMITH_TRACING is seen.
from dotenv import load_dotenv

load_dotenv()

# Suppress noisy third-party loggers
for _name in ("httpx", "httpcore", "openai", "urllib3", "langsmith", "langchain"):
    logging.getLogger(_name).setLevel(logging.WARNING)

from malibu.config import Settings
from malibu.server.agent import MalibuAgent
from malibu.telemetry.logging import setup_logging


async def main():
    settings = Settings(
        database_url="sqlite+aiosqlite:///test_runtime.db",
        jwt_secret="test-secret-key-for-tests-only-32ch",
        llm_model="openai:gpt-4o-mini",
        allowed_paths=["."],
        log_level="INFO",
    )
    setup_logging(settings)

    agent = MalibuAgent(settings)

    # Mock the ACP connection
    session_updates = []

    async def mock_session_update(*, session_id, update, source=None, **kwargs):
        session_updates.append(update)
        # Print update type for visibility
        update_type = type(update).__name__
        # Check title first — ToolCallStart has both content (often None) and title
        if hasattr(update, "title") and getattr(update, "title", None) is not None:
            print(f"  [{update_type}] {update.title}", flush=True)
        elif hasattr(update, "content") and update.content is not None:
            content = update.content
            if hasattr(content, "text"):
                print(f"  [{update_type}] {content.text}", end="", flush=True)
            else:
                print(f"  [{update_type}] {content}", end="", flush=True)
        elif hasattr(update, "status"):
            print(f"  [{update_type}] status={update.status}", flush=True)
        else:
            print(f"  [{update_type}]", flush=True)

    async def mock_request_permission(*, options, session_id, tool_call, **kwargs):
        # Auto-approve everything
        from acp.schema import AllowedOutcome
        if options:
            return type("Resp", (), {"outcome": AllowedOutcome(option_id=options[0].option_id)})()
        from acp.schema import DeniedOutcome
        return type("Resp", (), {"outcome": DeniedOutcome()})()

    mock_conn = MagicMock()
    mock_conn.session_update = mock_session_update
    mock_conn.request_permission = mock_request_permission
    agent.on_connect(mock_conn)

    # 1. Initialize
    print("=" * 60)
    print("1. INITIALIZE")
    print("=" * 60)
    resp = await agent.initialize(protocol_version=1)
    print(f"   Protocol version: {resp.protocol_version}")
    print(f"   Image support: {resp.agent_capabilities.prompt_capabilities.image}")
    print()

    # 2. New session
    print("=" * 60)
    print("2. NEW SESSION")
    print("=" * 60)
    session = await agent.new_session(cwd=".")
    sid = session.session_id
    print(f"   Session ID: {sid}")
    print(f"   Modes: {[m.name for m in session.modes.available_modes]}")
    print()

    # 3. Simple prompt (no tool calls expected)
    print("=" * 60)
    print("3. SIMPLE PROMPT — 'What is 2+2? Answer in one word.'")
    print("=" * 60)
    from acp import text_block as make_text_block
    prompt_blocks = [make_text_block("What is 2+2? Answer in one word.")]
    try:
        result = await asyncio.wait_for(
            agent.prompt(prompt=prompt_blocks, session_id=sid),
            timeout=30.0,
        )
        print(f"\n   Stop reason: {result.stop_reason}")
        print(f"   Session updates received: {len(session_updates)}")
    except asyncio.TimeoutError:
        print("\n   TIMEOUT after 30s")
    except Exception as e:
        print(f"\n   ERROR: {type(e).__name__}: {e}")
    print()

    # 4. Tool-using prompt (expect ls or similar)
    session_updates.clear()
    print("=" * 60)
    print("4. TOOL PROMPT — 'List the files in the current directory.'")
    print("=" * 60)
    prompt_blocks2 = [make_text_block("List the files in the current directory. Use the ls tool.")]
    try:
        result2 = await asyncio.wait_for(
            agent.prompt(prompt=prompt_blocks2, session_id=sid),
            timeout=60.0,
        )
        print(f"\n   Stop reason: {result2.stop_reason}")
        print(f"   Session updates received: {len(session_updates)}")
        tool_starts = [u for u in session_updates if type(u).__name__ == "ToolCallStart"]
        tool_progress = [u for u in session_updates if type(u).__name__ == "ToolCallProgress"]
        print(f"   Tool call starts: {len(tool_starts)}")
        print(f"   Tool call progress: {len(tool_progress)}")
    except asyncio.TimeoutError:
        print("\n   TIMEOUT after 60s")
    except Exception as e:
        print(f"\n   ERROR: {type(e).__name__}: {e}")
    print()

    print("=" * 60)
    print("RUNTIME SMOKE TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
