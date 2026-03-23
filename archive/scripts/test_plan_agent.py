#!/usr/bin/env python3
"""
Plan Agent Diagnostic Test Runner

Runs the PLAN agent against a real LLM backend and records every event
sequentially so you can inspect exactly what the agent sees, thinks, and does.

Outputs a detailed JSON trace file with:
  - Agent thinking/reasoning content
  - Tool calls (name, arguments the agent sent)
  - Tool results (output the tool returned, errors, duration)
  - Assistant text (what the agent says to the user)
  - Timing information for each event
  - The system prompt that was loaded

Usage:
    uv run python scripts/test_plan_agent.py

    # Custom prompt:
    uv run python scripts/test_plan_agent.py --prompt "Plan how to add OAuth2 to the auth module"

    # Custom output path:
    uv run python scripts/test_plan_agent.py --output /tmp/plan_trace.json

Environment:
    Requires MISTRAL_API_KEY (or whichever provider is configured).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vibe.core.agent_loop import AgentLoop
from vibe.core.agents.models import BuiltinAgentName
from vibe.core.config import VibeConfig
from vibe.core.config.harness_files import (
    init_harness_files_manager,
    reset_harness_files_manager,
)
from vibe.core.types import (
    AssistantEvent,
    BaseEvent,
    CompactEndEvent,
    CompactStartEvent,
    ReasoningEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolStreamEvent,
    UserMessageEvent,
)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_args(args: Any) -> dict[str, Any] | str | None:
    """Convert tool args (Pydantic model) to a JSON-safe dict."""
    if args is None:
        return None
    try:
        return args.model_dump(mode="json")
    except Exception:
        return str(args)


def _serialize_result(result: Any) -> dict[str, Any] | str | None:
    """Convert tool result (Pydantic model) to a JSON-safe dict."""
    if result is None:
        return None
    try:
        dumped = result.model_dump(mode="json")
        # Truncate very long string fields to keep the trace readable
        for key, value in dumped.items():
            if isinstance(value, str) and len(value) > 5000:
                dumped[key] = value[:5000] + f"\n... [TRUNCATED — {len(value)} chars total]"
        return dumped
    except Exception:
        s = str(result)
        if len(s) > 5000:
            return s[:5000] + f"\n... [TRUNCATED — {len(s)} chars total]"
        return s


def _event_to_record(event: BaseEvent, seq: int, elapsed: float) -> dict[str, Any]:
    """Convert a BaseEvent to a JSON-serializable trace record."""
    event_type = type(event).__name__
    record: dict[str, Any] = {
        "seq": seq,
        "elapsed_seconds": round(elapsed, 3),
        "event_type": event_type,
    }

    match event:
        case UserMessageEvent():
            record["content"] = event.content
            record["message_id"] = event.message_id

        case ReasoningEvent():
            record["thinking"] = event.content
            record["message_id"] = event.message_id

        case AssistantEvent():
            record["content"] = event.content
            record["stopped_by_middleware"] = event.stopped_by_middleware
            record["message_id"] = event.message_id

        case ToolCallEvent():
            record["tool_call_id"] = event.tool_call_id
            record["tool_name"] = event.tool_name
            record["tool_class"] = event.tool_class.__name__ if event.tool_class else None
            record["tool_call_index"] = event.tool_call_index
            record["args"] = _serialize_args(event.args)

        case ToolResultEvent():
            record["tool_call_id"] = event.tool_call_id
            record["tool_name"] = event.tool_name
            record["result"] = _serialize_result(event.result)
            record["error"] = event.error
            record["skipped"] = event.skipped
            record["skip_reason"] = event.skip_reason
            record["duration_seconds"] = round(event.duration, 3) if event.duration else None

        case ToolStreamEvent():
            record["tool_call_id"] = event.tool_call_id
            record["tool_name"] = event.tool_name
            record["message"] = event.message

        case CompactStartEvent():
            record["current_context_tokens"] = event.current_context_tokens
            record["threshold"] = event.threshold

        case CompactEndEvent():
            record["old_context_tokens"] = event.old_context_tokens
            record["new_context_tokens"] = event.new_context_tokens
            record["summary_length"] = event.summary_length

        case _:
            record["raw"] = str(event)

    return record


# ---------------------------------------------------------------------------
# Live console printer
# ---------------------------------------------------------------------------

_COLORS = {
    "reset":     "\033[0m",
    "bold":      "\033[1m",
    "dim":       "\033[2m",
    "cyan":      "\033[36m",
    "green":     "\033[32m",
    "yellow":    "\033[33m",
    "red":       "\033[31m",
    "magenta":   "\033[35m",
    "blue":      "\033[34m",
}


def _print_event(record: dict[str, Any]) -> None:
    """Print a single event record to the console with colors."""
    C = _COLORS
    seq = record["seq"]
    elapsed = record["elapsed_seconds"]
    etype = record["event_type"]
    prefix = f"{C['dim']}[{seq:>4}  {elapsed:>7.1f}s]{C['reset']}"

    match etype:
        case "UserMessageEvent":
            print(f"{prefix} {C['blue']}{C['bold']}USER:{C['reset']} {record['content'][:200]}")

        case "ReasoningEvent":
            thinking = record["thinking"]
            # Show first 300 chars of thinking
            preview = thinking[:300].replace("\n", " ")
            if len(thinking) > 300:
                preview += "..."
            print(f"{prefix} {C['magenta']}THINKING:{C['reset']} {preview}")

        case "AssistantEvent":
            content = record["content"]
            preview = content[:300].replace("\n", " ")
            if len(content) > 300:
                preview += "..."
            print(f"{prefix} {C['green']}ASSISTANT:{C['reset']} {preview}")

        case "ToolCallEvent":
            tool_name = record["tool_name"]
            args = record["args"]
            args_str = json.dumps(args, indent=None)[:200] if args else "{}"
            print(f"{prefix} {C['yellow']}TOOL CALL:{C['reset']} {C['bold']}{tool_name}{C['reset']}({args_str})")

        case "ToolResultEvent":
            tool_name = record["tool_name"]
            duration = record.get("duration_seconds", "?")
            error = record.get("error")
            skipped = record.get("skipped")
            if error:
                print(f"{prefix} {C['red']}TOOL ERROR:{C['reset']} {tool_name} [{duration}s] — {error[:200]}")
            elif skipped:
                reason = record.get("skip_reason", "unknown")
                print(f"{prefix} {C['yellow']}TOOL SKIPPED:{C['reset']} {tool_name} — {reason}")
            else:
                result = record.get("result")
                result_str = json.dumps(result, indent=None)[:200] if result else "(empty)"
                print(f"{prefix} {C['cyan']}TOOL RESULT:{C['reset']} {tool_name} [{duration}s] — {result_str}")

        case "ToolStreamEvent":
            msg = record["message"][:100]
            print(f"{prefix} {C['dim']}TOOL STREAM:{C['reset']} {record['tool_name']} — {msg}")

        case "CompactStartEvent":
            print(f"{prefix} {C['yellow']}COMPACT START:{C['reset']} {record['current_context_tokens']} tokens (threshold: {record['threshold']})")

        case "CompactEndEvent":
            print(f"{prefix} {C['yellow']}COMPACT END:{C['reset']} {record['old_context_tokens']} → {record['new_context_tokens']} tokens")

        case _:
            print(f"{prefix} {C['dim']}{etype}:{C['reset']} {record.get('raw', '')[:200]}")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def run_plan_agent(
    prompt: str,
    output_path: Path,
) -> dict[str, Any]:
    """Run the PLAN agent, stream events, and collect a full trace."""

    # ---- Setup harness files manager (required for prompt loading) ----
    reset_harness_files_manager()
    init_harness_files_manager("user", "project")

    # ---- Load real config from disk ----
    config = VibeConfig()

    # Override for plan agent: auto-approve all tools so the agent
    # can call read_file, grep, etc. without blocking on approval.
    from vibe.core.config import SessionLoggingConfig

    config = config.model_copy(update={
        "auto_approve": True,
        "session_logging": SessionLoggingConfig(enabled=False),
        "enable_update_checks": False,
    })

    # ---- Create agent loop with PLAN profile ----
    agent_loop = AgentLoop(
        config=config,
        agent_name=BuiltinAgentName.PLAN,
        enable_streaming=True,
    )

    # Auto-approve everything (no interactive approval needed)
    agent_loop.approval_callback = None

    # ---- Collect metadata ----
    system_prompt = ""
    if agent_loop.messages:
        for msg in agent_loop.messages:
            if msg.role.value == "system":
                system_prompt = msg.content[:10000]
                break

    available_tools = sorted(agent_loop.tool_manager.available_tools.keys())
    agent_profile = agent_loop.agent_profile

    # ---- Dump tool schemas (for debugging tool call issues) ----
    tool_schemas: dict[str, Any] = {}
    for tool_name, tool_cls in agent_loop.tool_manager.available_tools.items():
        try:
            model, _ = tool_cls._get_tool_args_results()
            schema = model.model_json_schema() if model else {}
            tool_schemas[tool_name] = {
                "description": getattr(tool_cls, "description", ""),
                "args_schema": schema,
            }
        except Exception as e:
            tool_schemas[tool_name] = {"error": str(e)}

    trace: dict[str, Any] = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt,
            "agent_name": agent_profile.name,
            "agent_display_name": agent_profile.display_name,
            "agent_safety": agent_profile.safety.value,
            "available_tools": available_tools,
            "tool_schemas": tool_schemas,
            "active_model": config.active_model,
            "system_prompt_preview": system_prompt[:3000] + ("..." if len(system_prompt) > 3000 else ""),
        },
        "events": [],
    }

    print(f"\n{'='*70}")
    print(f"  Plan Agent Diagnostic Test")
    print(f"{'='*70}")
    print(f"  Agent:   {agent_profile.display_name} ({agent_profile.name})")
    print(f"  Model:   {config.active_model}")
    print(f"  Tools:   {', '.join(available_tools)}")
    print(f"  Output:  {output_path}")
    print(f"  Prompt:  {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
    print(f"{'='*70}")
    print(f"\n  Tool Schemas:")
    for tname, tinfo in tool_schemas.items():
        if "error" in tinfo:
            print(f"    {tname}: ERROR — {tinfo['error']}")
        else:
            schema = tinfo.get("args_schema", {})
            required = schema.get("required", [])
            props = list(schema.get("properties", {}).keys())
            print(f"    {tname}: required={required}, props={props}")
    print()

    # ---- Run with timeout ----
    start_time = time.monotonic()
    seq = 0
    error_message = None

    try:
        async for event in agent_loop.act(prompt):
            elapsed = time.monotonic() - start_time
            seq += 1
            record = _event_to_record(event, seq, elapsed)
            trace["events"].append(record)
            _print_event(record)

    except KeyboardInterrupt:
        error_message = "Interrupted by user (Ctrl+C)"
        print(f"\n\033[33mInterrupted by user\033[0m")
    except Exception as e:
        error_message = f"{type(e).__name__}: {e}"
        print(f"\n\033[31mERROR: {e}\033[0m")

    total_elapsed = time.monotonic() - start_time

    # ---- Compute summary stats ----
    events = trace["events"]
    reasoning_events = [e for e in events if e["event_type"] == "ReasoningEvent"]
    assistant_events = [e for e in events if e["event_type"] == "AssistantEvent"]
    tool_call_events = [e for e in events if e["event_type"] == "ToolCallEvent"]
    tool_result_events = [e for e in events if e["event_type"] == "ToolResultEvent"]
    tool_errors = [e for e in tool_result_events if e.get("error")]
    tool_skipped = [e for e in tool_result_events if e.get("skipped")]

    full_thinking = "\n".join(e["thinking"] for e in reasoning_events)
    full_assistant = "\n".join(e["content"] for e in assistant_events)

    trace["summary"] = {
        "total_elapsed_seconds": round(total_elapsed, 2),
        "total_events": len(events),
        "reasoning_events": len(reasoning_events),
        "assistant_events": len(assistant_events),
        "tool_calls": len(tool_call_events),
        "tool_results": len(tool_result_events),
        "tool_errors": len(tool_errors),
        "tool_skipped": len(tool_skipped),
        "tools_called": sorted(set(e["tool_name"] for e in tool_call_events)),
        "error": error_message,
    }

    # ---- Store full thinking and assistant text separately for easy reading ----
    trace["full_thinking"] = full_thinking
    trace["full_assistant_text"] = full_assistant

    # ---- Write trace file ----
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- Print summary ----
    C = _COLORS
    print(f"\n{'='*70}")
    print(f"  {C['bold']}Summary{C['reset']}")
    print(f"{'='*70}")
    print(f"  Duration:         {total_elapsed:.1f}s")
    print(f"  Total events:     {len(events)}")
    print(f"  Thinking events:  {len(reasoning_events)} ({len(full_thinking)} chars)")
    print(f"  Assistant events: {len(assistant_events)} ({len(full_assistant)} chars)")
    print(f"  Tool calls:       {len(tool_call_events)}")
    print(f"  Tool results:     {len(tool_result_events)}")
    if tool_errors:
        print(f"  {C['red']}Tool errors:      {len(tool_errors)}{C['reset']}")
        for e in tool_errors:
            print(f"    - {e['tool_name']}: {e['error'][:100]}")
    if tool_skipped:
        print(f"  {C['yellow']}Tool skipped:     {len(tool_skipped)}{C['reset']}")
    if error_message:
        print(f"  {C['red']}Error:            {error_message}{C['reset']}")
    print(f"\n  Trace saved to: {output_path}")
    print(f"{'='*70}\n")

    return trace


def main() -> None:
    default_prompt = (
        "I want to refactor the agent loop to support multiple concurrent "
        "agent sessions. Explore the codebase to understand the current "
        "architecture, then create a detailed implementation plan."
    )

    parser = argparse.ArgumentParser(
        description="Run the PLAN agent and record a full diagnostic trace."
    )
    parser.add_argument(
        "--prompt", "-p",
        default=default_prompt,
        help="The user message to send to the plan agent.",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output path for the JSON trace file.",
    )
    args = parser.parse_args()

    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = PROJECT_ROOT / f"plan_trace_{timestamp}.json"

    asyncio.run(run_plan_agent(
        prompt=args.prompt,
        output_path=output_path,
    ))


if __name__ == "__main__":
    main()
