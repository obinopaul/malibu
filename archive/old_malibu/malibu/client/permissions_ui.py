"""Permission UI for the ACP client.

Renders permission prompts interactively in the terminal and collects
user decisions (approve / reject / always allow).
"""

from __future__ import annotations

import asyncio
from typing import Any

from acp.schema import (
    AllowedOutcome,
    DeniedOutcome,
    PermissionOption,
    RequestPermissionResponse,
    ToolCallUpdate,
)

from malibu.telemetry.logging import get_logger

log = get_logger(__name__)


async def _read_input(prompt: str) -> str:
    """Non-blocking console input."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))


async def interactive_permission_prompt(
    options: list[PermissionOption],
    tool_call: ToolCallUpdate,
) -> RequestPermissionResponse:
    """Display a permission request and collect a user decision via stdin."""
    print(f"\n{'=' * 60}")
    print(f"  Permission Request: {tool_call.title}")
    print(f"{'=' * 60}")

    if tool_call.raw_input:
        import json
        try:
            formatted = json.dumps(tool_call.raw_input, indent=2)
            # Truncate long inputs
            if len(formatted) > 500:
                formatted = formatted[:500] + "\n  ... (truncated)"
            print(f"  Input: {formatted}")
        except (TypeError, ValueError):
            print(f"  Input: {tool_call.raw_input}")

    print()
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt.name}")
    print(f"  [0] Cancel")
    print()

    try:
        choice = await _read_input("  Choose [1]: ")
        choice = choice.strip()
        if not choice:
            choice = "1"

        idx = int(choice)
        if idx == 0:
            return RequestPermissionResponse(
                outcome=DeniedOutcome(outcome="cancelled")
            )
        if 1 <= idx <= len(options):
            selected = options[idx - 1]
            return RequestPermissionResponse(
                outcome=AllowedOutcome(
                    outcome="selected",
                    option_id=selected.option_id,
                )
            )
        # Invalid choice — cancel
        return RequestPermissionResponse(
            outcome=DeniedOutcome(outcome="cancelled")
        )
    except (ValueError, EOFError, KeyboardInterrupt):
        return RequestPermissionResponse(
            outcome=DeniedOutcome(outcome="cancelled")
        )


async def auto_approve_permission(
    options: list[PermissionOption],
    tool_call: ToolCallUpdate,
) -> RequestPermissionResponse:
    """Auto-approve permission requests (for accept_everything mode)."""
    approve_option = next((o for o in options if o.kind == "allow_once"), options[0] if options else None)
    if approve_option:
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=approve_option.option_id)
        )
    return RequestPermissionResponse(
        outcome=DeniedOutcome(outcome="cancelled")
    )
