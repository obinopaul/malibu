#!/usr/bin/env python3
"""
Incremental Tool-Calling Diagnostic

Tests the PLAN agent's tool-calling pipeline in isolated, step-by-step tests
to pinpoint exactly where tool argument generation breaks down.

Test 1: ONE tool call   — can the agent make a single correct tool call?
Test 2: TWO tool calls  — does the agent maintain schema knowledge across turns?
Test 3: THREE tool calls — where exactly does degradation begin?

Each test captures:
  - The exact messages sent to the LLM (including tool schemas)
  - The model's response (tool calls with arguments)
  - The tool results sent back
  - The next model response

Usage:
    uv run python scripts/test_tool_calling.py
    uv run python scripts/test_tool_calling.py --test 1       # Only run test 1
    uv run python scripts/test_tool_calling.py --test 2       # Only run test 2
    uv run python scripts/test_tool_calling.py --test 3       # Only run test 3
    uv run python scripts/test_tool_calling.py --output /tmp/tool_diag.json

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
from uuid import uuid4

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

C = {
    "reset":   "\033[0m",
    "bold":    "\033[1m",
    "dim":     "\033[2m",
    "cyan":    "\033[36m",
    "green":   "\033[32m",
    "yellow":  "\033[33m",
    "red":     "\033[31m",
    "magenta": "\033[35m",
    "blue":    "\033[34m",
}


def _header(text: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {C['bold']}{text}{C['reset']}")
    print(f"{'='*70}")


def _info(label: str, value: str) -> None:
    print(f"  {C['cyan']}{label:<20}{C['reset']} {value}")


def _ok(text: str) -> None:
    print(f"  {C['green']}✓ {text}{C['reset']}")


def _fail(text: str) -> None:
    print(f"  {C['red']}✗ {text}{C['reset']}")


def _warn(text: str) -> None:
    print(f"  {C['yellow']}⚠ {text}{C['reset']}")


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def setup_agent_loop():
    """Create a minimal AgentLoop configured for the PLAN agent."""
    from vibe.core.agent_loop import AgentLoop
    from vibe.core.agents.models import BuiltinAgentName
    from vibe.core.config import VibeConfig, SessionLoggingConfig
    from vibe.core.config.harness_files import (
        init_harness_files_manager,
        reset_harness_files_manager,
    )

    reset_harness_files_manager()
    init_harness_files_manager("user", "project")

    config = VibeConfig()
    config = config.model_copy(update={
        "auto_approve": True,
        "session_logging": SessionLoggingConfig(enabled=False),
        "enable_update_checks": False,
    })

    agent_loop = AgentLoop(
        config=config,
        agent_name=BuiltinAgentName.PLAN,
        enable_streaming=True,
    )
    agent_loop.approval_callback = None
    return agent_loop


def get_tool_schemas(agent_loop) -> dict[str, Any]:
    """Extract tool schemas from the agent loop's tool manager."""
    schemas = {}
    for tool_name, tool_cls in agent_loop.tool_manager.available_tools.items():
        try:
            model, _ = tool_cls._get_tool_args_results()
            schema = model.model_json_schema() if model else {}
            schemas[tool_name] = {
                "description": getattr(tool_cls, "description", ""),
                "args_schema": schema,
            }
        except Exception as e:
            schemas[tool_name] = {"error": str(e)}
    return schemas


# ---------------------------------------------------------------------------
# Low-level LLM call wrapper — bypasses LangChain entirely
# ---------------------------------------------------------------------------

def _msgs_to_vibe(messages: list[dict[str, Any]]):
    """Convert dict messages to Vibe LLMMessage format."""
    from vibe.core.types import LLMMessage, Role, ToolCall as VToolCall, FunctionCall

    vibe_messages = []
    for msg in messages:
        role = Role(msg["role"])
        lmsg = LLMMessage(role=role, content=msg.get("content", ""))
        if msg.get("tool_call_id"):
            lmsg = LLMMessage(
                role=role,
                content=msg.get("content", ""),
                tool_call_id=msg["tool_call_id"],
                name=msg.get("name"),
            )
        if msg.get("tool_calls"):
            tc_list = []
            for tc in msg["tool_calls"]:
                tc_list.append(VToolCall(
                    id=tc["id"],
                    type="function",
                    function=FunctionCall(
                        name=tc["function"]["name"],
                        arguments=json.dumps(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], dict) else tc["function"]["arguments"],
                    ),
                ))
            lmsg = LLMMessage(
                role=role,
                content=msg.get("content", ""),
                tool_calls=tc_list,
            )
        vibe_messages.append(lmsg)
    return vibe_messages


def _tools_to_vibe(tools: list[dict[str, Any]] | None):
    """Convert dict tools to Vibe AvailableTool format."""
    from vibe.core.types import AvailableTool, AvailableFunction

    if not tools:
        return None
    vibe_tools = []
    for t in tools:
        func = t.get("function", t)
        vibe_tools.append(AvailableTool(
            function=AvailableFunction(
                name=func["name"],
                description=func.get("description", ""),
                parameters=func.get("parameters", {}),
            )
        ))
    return vibe_tools


def _extract_tool_calls_from_msg(response_msg) -> list[dict[str, Any]]:
    """Extract tool calls from an LLMMessage into a serializable list."""
    tool_calls_out = []
    if response_msg.tool_calls:
        for tc in response_msg.tool_calls:
            args_raw = tc.function.arguments or "{}"
            try:
                args_parsed = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args_parsed = args_raw
            tool_calls_out.append({
                "id": tc.id,
                "name": tc.function.name,
                "arguments": args_parsed,
                "arguments_raw": args_raw,
            })
    return tool_calls_out


async def raw_llm_call(
    agent_loop,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Make a raw LLM call using STREAMING (the actual code path used by the agent).

    Uses complete_streaming() and aggregates chunks, exactly like the real
    DeepAgentRuntime does. This ensures we test the same parsing path.

    Also captures per-chunk data to see if tool calls appear in intermediate
    chunks but get lost in aggregation.
    """
    from vibe.core.types import LLMChunk

    vibe_messages = _msgs_to_vibe(messages)
    vibe_tools = _tools_to_vibe(tools)

    active_model = agent_loop.config.get_active_model()
    provider = agent_loop.config.get_provider_for_model(active_model)

    start = time.monotonic()
    chunk_log = []  # Log each streaming chunk for debugging
    aggregated = None

    async for chunk in agent_loop.backend.complete_streaming(
        model=active_model,
        messages=vibe_messages,
        temperature=active_model.temperature,
        tools=vibe_tools,
        tool_choice=None,
        extra_headers=agent_loop._get_extra_headers(provider),
        max_tokens=None,
        metadata=None,
    ):
        # Log each chunk
        chunk_info = {
            "text": chunk.message.content or "",
            "reasoning": chunk.message.reasoning_content or "",
            "tool_calls": _extract_tool_calls_from_msg(chunk.message),
            "prompt_tokens": chunk.usage.prompt_tokens if chunk.usage else 0,
            "completion_tokens": chunk.usage.completion_tokens if chunk.usage else 0,
        }
        if any(v for v in chunk_info.values()):  # Only log non-empty chunks
            chunk_log.append(chunk_info)

        if aggregated is None:
            aggregated = chunk
        else:
            aggregated += chunk

    elapsed = time.monotonic() - start

    # Extract from aggregated result
    if aggregated:
        response_msg = aggregated.message
        tool_calls_out = _extract_tool_calls_from_msg(response_msg)
        text = response_msg.content or ""
        reasoning = response_msg.reasoning_content or ""
        usage = {
            "prompt_tokens": aggregated.usage.prompt_tokens if aggregated.usage else 0,
            "completion_tokens": aggregated.usage.completion_tokens if aggregated.usage else 0,
        }
    else:
        tool_calls_out = []
        text = ""
        reasoning = ""
        usage = {"prompt_tokens": 0, "completion_tokens": 0}

    # Also check: did any individual chunk have tool calls that got lost?
    chunks_with_tool_calls = [c for c in chunk_log if c["tool_calls"]]

    return {
        "request": {
            "messages_count": len(messages),
            "messages": messages,
            "tools_count": len(tools) if tools else 0,
            "tools": tools,
        },
        "response": {
            "text": text,
            "reasoning": reasoning,
            "tool_calls": tool_calls_out,
            "has_tool_calls": bool(tool_calls_out),
        },
        "streaming_debug": {
            "total_chunks": len(chunk_log),
            "chunks_with_tool_calls": len(chunks_with_tool_calls),
            "chunk_log": chunk_log[:20],  # First 20 chunks for debugging
        },
        "timing": {
            "elapsed_seconds": round(elapsed, 3),
        },
        "usage": usage,
    }


async def raw_llm_call_non_streaming(
    agent_loop,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Make a raw LLM call using NON-STREAMING complete().

    This is expected to be BROKEN for the openai-responses adapter because
    it doesn't handle the non-streaming 'response' type.
    """
    vibe_messages = _msgs_to_vibe(messages)
    vibe_tools = _tools_to_vibe(tools)

    active_model = agent_loop.config.get_active_model()
    provider = agent_loop.config.get_provider_for_model(active_model)

    start = time.monotonic()
    result = await agent_loop.backend.complete(
        model=active_model,
        messages=vibe_messages,
        temperature=active_model.temperature,
        tools=vibe_tools,
        tool_choice=None,
        extra_headers=agent_loop._get_extra_headers(provider),
        max_tokens=None,
        metadata=None,
    )
    elapsed = time.monotonic() - start

    response_msg = result.message
    tool_calls_out = _extract_tool_calls_from_msg(response_msg)

    return {
        "request": {
            "messages_count": len(messages),
            "messages": messages,
            "tools_count": len(tools) if tools else 0,
        },
        "response": {
            "text": response_msg.content or "",
            "reasoning": response_msg.reasoning_content or "",
            "tool_calls": tool_calls_out,
            "has_tool_calls": bool(tool_calls_out),
        },
        "timing": {"elapsed_seconds": round(elapsed, 3)},
        "usage": {
            "prompt_tokens": result.usage.prompt_tokens if result.usage else 0,
            "completion_tokens": result.usage.completion_tokens if result.usage else 0,
        },
    }


# ---------------------------------------------------------------------------
# Build tool schemas for the LLM
# ---------------------------------------------------------------------------

def build_tool_defs(agent_loop) -> list[dict[str, Any]]:
    """Build OpenAI-format tool definitions from the agent's available tools."""
    from vibe.core.deepagent.adapters import _build_enhanced_description

    tool_defs = []
    for tool_name, tool_cls in agent_loop.tool_manager.available_tools.items():
        model, _ = tool_cls._get_tool_args_results()
        if model is None:
            continue
        schema = model.model_json_schema()
        # Remove unnecessary schema fields that confuse some models
        schema.pop("title", None)

        enhanced_desc = _build_enhanced_description(tool_name, tool_cls, model)

        tool_defs.append({
            "type": "function",
            "function": {
                "name": tool_name,
                "description": enhanced_desc,
                "parameters": schema,
            },
        })
    return tool_defs


# ---------------------------------------------------------------------------
# Fake tool results (for controlled testing)
# ---------------------------------------------------------------------------

FAKE_TOOL_RESULTS = {
    "read_file": lambda args: f"# pyproject.toml\n[project]\nname = \"malibu\"\nversion = \"0.1.0\"\n\n[project.dependencies]\nlangchain = \">=0.3\"\npydantic = \">=2.0\"\n",
    "grep": lambda args: f"Found 3 matches for '{args.get('pattern', '???')}':\n  vibe/core/agent_loop.py:42: class AgentLoop:\n  vibe/core/agent_loop.py:135: async def act(self, prompt: str)\n  vibe/core/agent_loop.py:200: def _handle_tool_call(self, ...)\n",
    "todo": lambda args: f"Todo list updated successfully. Action: {args.get('action', 'unknown')}",
    "task": lambda args: f"Task dispatched: {args.get('task', 'unknown')[:100]}",
    "ast_grep": lambda args: f"AST search for '{args.get('pattern', '???')}' found 0 matches.",
}


def fake_tool_result(tool_name: str, args: dict) -> str:
    """Return a fake but realistic tool result for testing."""
    handler = FAKE_TOOL_RESULTS.get(tool_name)
    if handler:
        return handler(args)
    return f"Tool '{tool_name}' executed successfully with args: {json.dumps(args)}"


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------

async def test_single_tool_call(agent_loop, tool_defs: list[dict]) -> dict[str, Any]:
    """Test 1: Can the agent make ONE correct tool call? (via streaming)

    Sends a simple prompt that should trigger exactly one tool call (read_file).
    Uses complete_streaming() — the actual code path the agent uses.
    """
    _header("TEST 1: Single Tool Call (Streaming)")
    _info("Goal", "Can the agent make one correct tool call via streaming?")
    _info("Prompt", "Read the file pyproject.toml and tell me the project name")
    print()

    system_prompt = (
        "You are a planning assistant. You have access to tools for reading files "
        "and searching code. Use the tools to answer the user's questions.\n\n"
        "IMPORTANT: When calling tools, you MUST provide all required arguments "
        "as a JSON object. Tool names are simple strings like 'read_file', not "
        "namespaced like 'functions.read_file'."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Read the file pyproject.toml and tell me the project name."},
    ]

    # Call 1: Expect a tool call
    print(f"  {C['dim']}--- LLM Call 1 (streaming): Initial prompt ---{C['reset']}")
    result1 = await raw_llm_call(agent_loop, messages, tool_defs)

    call1_ok = False
    call1_tool_calls = result1["response"]["tool_calls"]

    # Show streaming debug info
    sd = result1.get("streaming_debug", {})
    print(f"  {C['dim']}Streaming: {sd.get('total_chunks', 0)} chunks, {sd.get('chunks_with_tool_calls', 0)} had tool calls{C['reset']}")
    if sd.get("chunks_with_tool_calls", 0) > 0:
        _ok(f"Tool calls SEEN in streaming chunks")
    elif sd.get("total_chunks", 0) > 0:
        _warn(f"Streaming chunks received but NONE had tool calls")
        # Show what the chunks contained
        for i, chunk in enumerate(sd.get("chunk_log", [])[:5]):
            text_preview = chunk.get("text", "")[:80]
            tc_count = len(chunk.get("tool_calls", []))
            print(f"    Chunk {i}: text='{text_preview}' tool_calls={tc_count}")

    if call1_tool_calls:
        for tc in call1_tool_calls:
            args_empty = not tc["arguments"] or tc["arguments"] == {}
            print(f"  Tool call: {C['bold']}{tc['name']}{C['reset']}({json.dumps(tc['arguments'])})")
            if args_empty:
                _fail(f"Empty arguments for {tc['name']}!")
            else:
                _ok(f"Arguments provided for {tc['name']}")
                call1_ok = True
    else:
        text_preview = result1["response"]["text"][:300]
        print(f"  No tool call — model responded with text: {text_preview}")
        _warn("Expected a tool call but got text response")

    if result1["response"]["reasoning"]:
        thinking = result1["response"]["reasoning"][:300].replace("\n", " ")
        print(f"  {C['magenta']}Thinking:{C['reset']} {thinking}{'...' if len(result1['response']['reasoning']) > 300 else ''}")

    print(f"  {C['dim']}Tokens: {result1['usage']['prompt_tokens']} in, {result1['usage']['completion_tokens']} out, {result1['timing']['elapsed_seconds']}s{C['reset']}")

    return {
        "test": "single_tool_call_streaming",
        "passed": call1_ok,
        "llm_calls": [result1],
    }


async def test_two_tool_calls(agent_loop, tool_defs: list[dict]) -> dict[str, Any]:
    """Test 2: Can the agent make TWO correct tool calls in sequence?

    Sends a prompt, gets a tool call, feeds back a fake result,
    then checks if the second response also has correct tool args.
    """
    _header("TEST 2: Two Sequential Tool Calls")
    _info("Goal", "Does the agent maintain schema knowledge across turns?")
    _info("Prompt", "Read pyproject.toml, then grep for 'AgentLoop'")
    print()

    system_prompt = (
        "You are a planning assistant. You have access to tools for reading files "
        "and searching code. Use the tools to answer the user's questions.\n\n"
        "IMPORTANT: When calling tools, you MUST provide all required arguments "
        "as a JSON object. Tool names are simple strings like 'read_file', not "
        "namespaced like 'functions.read_file'."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            "I need you to do two things:\n"
            "1. First, read the file pyproject.toml\n"
            "2. Then, grep for the pattern 'AgentLoop' in the vibe/ directory\n"
            "Do them one at a time."
        )},
    ]

    results = []
    all_ok = True

    # Call 1: Expect first tool call (read_file)
    print(f"  {C['dim']}--- LLM Call 1: Initial prompt ---{C['reset']}")
    result1 = await raw_llm_call(agent_loop, messages, tool_defs)
    results.append(result1)

    call1_tool_calls = result1["response"]["tool_calls"]
    if not call1_tool_calls:
        _fail("No tool call in first response")
        return {"test": "two_tool_calls", "passed": False, "llm_calls": results}

    tc1 = call1_tool_calls[0]
    args_empty = not tc1["arguments"] or tc1["arguments"] == {}
    print(f"  Tool call: {C['bold']}{tc1['name']}{C['reset']}({json.dumps(tc1['arguments'])})")
    if args_empty:
        _fail(f"Empty arguments for {tc1['name']} on FIRST call!")
        all_ok = False
    else:
        _ok(f"First call correct: {tc1['name']}")

    if result1["response"]["reasoning"]:
        thinking = result1["response"]["reasoning"][:200].replace("\n", " ")
        print(f"  {C['magenta']}Thinking:{C['reset']} {thinking}...")
    print(f"  {C['dim']}Tokens: {result1['usage']['prompt_tokens']} in, {result1['usage']['completion_tokens']} out{C['reset']}")

    # Build the conversation with the tool result
    fake_result = fake_tool_result(tc1["name"], tc1["arguments"])

    # Add the assistant's tool call and the tool result to messages
    messages.append({
        "role": "assistant",
        "content": result1["response"]["text"],
        "tool_calls": [{
            "id": tc1["id"],
            "function": {
                "name": tc1["name"],
                "arguments": tc1["arguments"],
            },
        }],
    })
    messages.append({
        "role": "tool",
        "content": fake_result,
        "tool_call_id": tc1["id"],
        "name": tc1["name"],
    })

    print(f"\n  {C['dim']}--- Injecting fake tool result ({len(fake_result)} chars) ---{C['reset']}")
    print(f"  {C['dim']}{fake_result[:150]}{C['reset']}")

    # Call 2: Expect second tool call (grep)
    print(f"\n  {C['dim']}--- LLM Call 2: After first tool result ---{C['reset']}")
    result2 = await raw_llm_call(agent_loop, messages, tool_defs)
    results.append(result2)

    call2_tool_calls = result2["response"]["tool_calls"]
    if not call2_tool_calls:
        text = result2["response"]["text"][:200]
        print(f"  No tool call — model responded with text: {text}")
        _warn("Expected second tool call but got text")
        # Not necessarily a failure — model might have answered directly
    else:
        tc2 = call2_tool_calls[0]
        args_empty = not tc2["arguments"] or tc2["arguments"] == {}
        print(f"  Tool call: {C['bold']}{tc2['name']}{C['reset']}({json.dumps(tc2['arguments'])})")
        if args_empty:
            _fail(f"Empty arguments for {tc2['name']} on SECOND call!")
            all_ok = False
        else:
            _ok(f"Second call correct: {tc2['name']}")

    if result2["response"]["reasoning"]:
        thinking = result2["response"]["reasoning"][:200].replace("\n", " ")
        print(f"  {C['magenta']}Thinking:{C['reset']} {thinking}...")
    print(f"  {C['dim']}Tokens: {result2['usage']['prompt_tokens']} in, {result2['usage']['completion_tokens']} out{C['reset']}")

    return {
        "test": "two_tool_calls",
        "passed": all_ok,
        "llm_calls": results,
    }


async def test_three_tool_calls(agent_loop, tool_defs: list[dict]) -> dict[str, Any]:
    """Test 3: Can the agent make THREE correct tool calls in sequence?

    This is where degradation was observed. We test:
    read_file → grep → todo (write action)
    """
    _header("TEST 3: Three Sequential Tool Calls")
    _info("Goal", "Where does context degradation begin?")
    _info("Prompt", "Read file, grep, then create a todo")
    print()

    system_prompt = (
        "You are a planning assistant. You have access to tools for reading files, "
        "searching code, and managing todos. Use the tools to answer the user's questions.\n\n"
        "IMPORTANT: When calling tools, you MUST provide all required arguments "
        "as a JSON object. Tool names are simple strings like 'read_file', not "
        "namespaced like 'functions.read_file'.\n\n"
        "Available tools:\n"
        "- read_file: Read a file. Required args: {\"file_path\": \"path/to/file\"}\n"
        "- grep: Search for patterns. Required args: {\"pattern\": \"search term\"}\n"
        "- todo: Manage todo lists. Required args: {\"action\": \"read\" or \"write\"}\n"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            "Please do the following three steps, one at a time:\n"
            "1. Read the file pyproject.toml\n"
            "2. Grep for 'AgentLoop' in vibe/\n"
            "3. Create a todo item with a summary of what you found\n"
            "Do each step one at a time. Wait for each result before proceeding."
        )},
    ]

    results = []
    call_results = []  # Track pass/fail for each call

    for step in range(1, 4):
        print(f"\n  {C['dim']}--- LLM Call {step}: Step {step} of 3 ---{C['reset']}")
        result = await raw_llm_call(agent_loop, messages, tool_defs)
        results.append(result)

        tool_calls = result["response"]["tool_calls"]

        if not tool_calls:
            text = result["response"]["text"][:200]
            print(f"  No tool call — text: {text}")
            _warn(f"Step {step}: No tool call")
            call_results.append({"step": step, "ok": False, "reason": "no_tool_call"})
            # If the model gives text instead of a tool call, nudge it
            messages.append({
                "role": "assistant",
                "content": result["response"]["text"],
            })
            messages.append({
                "role": "user",
                "content": f"Please use the appropriate tool for step {step}. Remember to provide all required arguments.",
            })
            continue

        tc = tool_calls[0]
        args_empty = not tc["arguments"] or tc["arguments"] == {}
        print(f"  Tool call: {C['bold']}{tc['name']}{C['reset']}({json.dumps(tc['arguments'])})")

        if args_empty:
            _fail(f"Step {step}: Empty arguments for {tc['name']}!")
            call_results.append({
                "step": step, "ok": False, "reason": "empty_args",
                "tool_name": tc["name"],
            })
        else:
            _ok(f"Step {step}: Correct call to {tc['name']}")
            call_results.append({
                "step": step, "ok": True,
                "tool_name": tc["name"],
                "args": tc["arguments"],
            })

        if result["response"]["reasoning"]:
            thinking = result["response"]["reasoning"][:200].replace("\n", " ")
            print(f"  {C['magenta']}Thinking:{C['reset']} {thinking}...")
        print(f"  {C['dim']}Tokens: {result['usage']['prompt_tokens']} in, {result['usage']['completion_tokens']} out{C['reset']}")

        # Add tool call + fake result to conversation
        fake_result = fake_tool_result(tc["name"], tc["arguments"])
        messages.append({
            "role": "assistant",
            "content": result["response"]["text"],
            "tool_calls": [{
                "id": tc["id"],
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                },
            }],
        })
        messages.append({
            "role": "tool",
            "content": fake_result,
            "tool_call_id": tc["id"],
            "name": tc["name"],
        })
        print(f"  {C['dim']}Injected fake result ({len(fake_result)} chars){C['reset']}")

    all_ok = all(cr["ok"] for cr in call_results)

    # Summary
    print(f"\n  {C['bold']}Step results:{C['reset']}")
    for cr in call_results:
        status = f"{C['green']}PASS{C['reset']}" if cr["ok"] else f"{C['red']}FAIL ({cr['reason']}){C['reset']}"
        tool = cr.get("tool_name", "?")
        print(f"    Step {cr['step']}: {status} — {tool}")

    return {
        "test": "three_tool_calls",
        "passed": all_ok,
        "call_results": call_results,
        "llm_calls": results,
    }


# ---------------------------------------------------------------------------
# Also test through the actual LangChain pipeline for comparison
# ---------------------------------------------------------------------------

async def test_langchain_single_call(agent_loop, tool_defs: list[dict]) -> dict[str, Any]:
    """Test 4: Same as Test 1, but through VibeChatModel + LangChain streaming.

    Uses _astream (which is what LangGraph actually calls), not ainvoke.
    This tests whether the LangChain/LangGraph layer introduces the problem.
    """
    _header("TEST 4: Single Tool Call via LangChain (streaming)")
    _info("Goal", "Does the LangChain layer introduce the empty-args bug?")
    print()

    from vibe.core.deepagent.adapters import build_langchain_tools, _tool_to_openai_schema
    from vibe.core.deepagent.adapters import VibeChatModel
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessageChunk

    events_captured = []

    async def emit_event(event):
        events_captured.append(event)

    def noop():
        pass

    # Build LangChain tools
    lc_tools = build_langchain_tools(
        agent_loop, emit_event=emit_event,
        on_tool_started=noop, on_tool_finished=noop,
    )

    print(f"  Built {len(lc_tools)} LangChain tools:")
    for t in lc_tools:
        schema = _tool_to_openai_schema(t)
        func = schema.get("function", {}) if schema else {}
        params = func.get("parameters", {})
        required = params.get("required", [])
        props = list(params.get("properties", {}).keys())
        print(f"    {t.name}: required={required}, props={props}")

    model = VibeChatModel(loop=agent_loop)
    model_with_tools = model.bind_tools(lc_tools)

    system_msg = SystemMessage(content=(
        "You are a planning assistant. Read the file pyproject.toml. "
        "You MUST use the read_file tool with the file_path argument."
    ))
    user_msg = HumanMessage(content="Read the file pyproject.toml and tell me the project name.")

    # Use _astream (the actual path LangGraph uses)
    print(f"\n  {C['dim']}--- LLM Call via LangChain _astream ---{C['reset']}")
    start = time.monotonic()

    chunks_collected = []
    aggregated = None
    async for chunk_gen in model_with_tools.astream([system_msg, user_msg]):
        chunk_info = {
            "content": chunk_gen.content or "",
            "tool_calls": getattr(chunk_gen, "tool_calls", []),
            "tool_call_chunks": getattr(chunk_gen, "tool_call_chunks", []),
        }
        chunks_collected.append(chunk_info)
        if aggregated is None:
            aggregated = chunk_gen
        else:
            aggregated += chunk_gen

    elapsed = time.monotonic() - start

    # Inspect aggregated result
    tool_calls = getattr(aggregated, "tool_calls", []) if aggregated else []
    tool_call_chunks_seen = sum(1 for c in chunks_collected if c["tool_call_chunks"])
    text = (aggregated.content or "") if aggregated else ""

    print(f"  {C['dim']}Chunks: {len(chunks_collected)} total, {tool_call_chunks_seen} had tool_call_chunks{C['reset']}")

    # Show first few chunks that have tool_call_chunks
    for i, c in enumerate(chunks_collected):
        if c["tool_call_chunks"]:
            print(f"    Chunk {i}: tool_call_chunks={json.dumps(c['tool_call_chunks'], default=str)[:200]}")
            if i > 5:
                print(f"    ... and more")
                break

    call_ok = False
    if tool_calls:
        for tc in tool_calls:
            args = tc.get("args", {})
            name = tc.get("name", "?")
            args_empty = not args or args == {}
            print(f"  Tool call: {C['bold']}{name}{C['reset']}({json.dumps(args)})")
            if args_empty:
                _fail(f"Empty arguments for {name} via LangChain!")
            else:
                _ok(f"Arguments correct for {name} via LangChain")
                call_ok = True
    else:
        print(f"  No tool call — text: {text[:200]}")
        _warn("Expected tool call but got text")

    print(f"  {C['dim']}{elapsed:.2f}s{C['reset']}")

    return {
        "test": "langchain_single_call",
        "passed": call_ok,
        "tool_calls": [{"name": tc.get("name"), "args": tc.get("args")} for tc in tool_calls],
        "text": text[:500],
        "elapsed": round(elapsed, 3),
        "chunks_total": len(chunks_collected),
        "chunks_with_tool_call_chunks": tool_call_chunks_seen,
    }


async def test_non_streaming_comparison(agent_loop, tool_defs: list[dict]) -> dict[str, Any]:
    """Test 5: Compare streaming vs non-streaming to confirm the parsing bug.

    We expect non-streaming to FAIL (drops tool calls) and streaming to PASS.
    This confirms the root cause is in the OpenAI Responses adapter.
    """
    _header("TEST 5: Streaming vs Non-Streaming Comparison")
    _info("Goal", "Confirm non-streaming adapter drops tool calls")
    print()

    system_prompt = (
        "You are a planning assistant. You have tools. "
        "Read the file pyproject.toml using the read_file tool."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Read pyproject.toml"},
    ]

    # Non-streaming
    print(f"  {C['dim']}--- Non-streaming (complete()) ---{C['reset']}")
    try:
        ns_result = await raw_llm_call_non_streaming(agent_loop, messages, tool_defs)
        ns_tc = ns_result["response"]["tool_calls"]
        ns_text = ns_result["response"]["text"][:200]
        ns_tokens = ns_result["usage"]["completion_tokens"]
        if ns_tc:
            _ok(f"Non-streaming: {len(ns_tc)} tool calls, {ns_tokens} tokens")
            for tc in ns_tc:
                print(f"    {tc['name']}({json.dumps(tc['arguments'])})")
        else:
            _fail(f"Non-streaming: NO tool calls despite {ns_tokens} completion tokens")
            if ns_text:
                print(f"    Text: {ns_text}")
            else:
                print(f"    (both text and tool_calls are empty — response dropped by parser)")
    except Exception as e:
        _fail(f"Non-streaming error: {e}")
        ns_result = {"error": str(e)}

    # Streaming
    print(f"\n  {C['dim']}--- Streaming (complete_streaming()) ---{C['reset']}")
    s_result = await raw_llm_call(agent_loop, messages, tool_defs)
    s_tc = s_result["response"]["tool_calls"]
    s_text = s_result["response"]["text"][:200]
    s_tokens = s_result["usage"]["completion_tokens"]
    sd = s_result.get("streaming_debug", {})

    if s_tc:
        _ok(f"Streaming: {len(s_tc)} tool calls, {s_tokens} tokens")
        for tc in s_tc:
            print(f"    {tc['name']}({json.dumps(tc['arguments'])})")
    else:
        _fail(f"Streaming: NO tool calls despite {s_tokens} completion tokens")
        print(f"    Chunks: {sd.get('total_chunks', 0)}, with tool calls: {sd.get('chunks_with_tool_calls', 0)}")
        if s_text:
            print(f"    Text: {s_text}")

    # Analysis
    print(f"\n  {C['bold']}Analysis:{C['reset']}")
    ns_has = bool(ns_result.get("response", {}).get("tool_calls")) if isinstance(ns_result, dict) else False
    s_has = bool(s_tc)

    if s_has and not ns_has:
        _ok("CONFIRMED: Streaming works, non-streaming drops tool calls")
        _info("Root cause", "OpenAI Responses adapter missing 'response' type handler")
    elif s_has and ns_has:
        _ok("Both work — non-streaming is NOT the issue")
    elif not s_has and not ns_has:
        _fail("NEITHER works — issue is deeper (model or request format)")
    else:
        _warn("Non-streaming works but streaming doesn't — unexpected")

    return {
        "test": "non_streaming_comparison",
        "passed": s_has,  # Streaming should work
        "streaming_tool_calls": s_tc,
        "non_streaming_tool_calls": ns_result.get("response", {}).get("tool_calls", []) if isinstance(ns_result, dict) else [],
        "streaming_result": s_result,
        "non_streaming_result": ns_result,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_tests(test_num: int | None, output_path: Path) -> None:
    agent_loop = setup_agent_loop()

    _header("Tool-Calling Diagnostic")
    _info("Model", str(agent_loop.config.active_model))
    _info("Agent", str(agent_loop.agent_profile.name))

    tool_schemas = get_tool_schemas(agent_loop)
    tool_defs = build_tool_defs(agent_loop)

    _info("Tools", ", ".join(tool_schemas.keys()))
    print()
    for tname, tinfo in tool_schemas.items():
        if "error" in tinfo:
            print(f"    {C['red']}{tname}: ERROR — {tinfo['error']}{C['reset']}")
        else:
            schema = tinfo.get("args_schema", {})
            required = schema.get("required", [])
            print(f"    {tname}: required={required}")

    trace = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": str(agent_loop.config.active_model),
            "tool_schemas": tool_schemas,
            "tool_defs_sent_to_llm": tool_defs,
        },
        "tests": {},
    }

    tests = {
        1: ("single_tool_call", test_single_tool_call),
        2: ("two_tool_calls", test_two_tool_calls),
        3: ("three_tool_calls", test_three_tool_calls),
        4: ("langchain_single_call", test_langchain_single_call),
        5: ("non_streaming_comparison", test_non_streaming_comparison),
    }

    for num, (name, func) in tests.items():
        if test_num is not None and num != test_num:
            continue
        try:
            result = await func(agent_loop, tool_defs)
            trace["tests"][name] = result
            if result["passed"]:
                _ok(f"TEST {num} PASSED")
            else:
                _fail(f"TEST {num} FAILED")
        except Exception as e:
            _fail(f"TEST {num} ERROR: {type(e).__name__}: {e}")
            trace["tests"][name] = {"error": f"{type(e).__name__}: {e}"}
            import traceback
            traceback.print_exc()

    # Summary
    _header("Overall Results")
    for name, result in trace["tests"].items():
        if isinstance(result, dict) and "passed" in result:
            status = f"{C['green']}PASS{C['reset']}" if result["passed"] else f"{C['red']}FAIL{C['reset']}"
        else:
            status = f"{C['red']}ERROR{C['reset']}"
        print(f"  {name}: {status}")

    # Write trace
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(trace, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n  Trace saved to: {output_path}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Incremental tool-calling diagnostic for the PLAN agent."
    )
    parser.add_argument(
        "--test", "-t",
        type=int,
        default=None,
        choices=[1, 2, 3, 4, 5],
        help="Run only this test number (1-5). Default: run all.",
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
        output_path = PROJECT_ROOT / f"tool_diag_{timestamp}.json"

    asyncio.run(run_tests(args.test, output_path))


if __name__ == "__main__":
    main()
