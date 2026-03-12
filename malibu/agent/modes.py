"""Agent modes and HITL interrupt configuration.

Defines the available modes (ACP ``SessionModeState``) and the
``interrupt_on`` dict that ``HumanInTheLoopMiddleware`` uses in each mode.

Per the langchain-middleware skill, ``interrupt_on`` maps tool names to
``{"allowed_decisions": [...]}`` or ``False`` to skip HITL for that tool.
"""

from __future__ import annotations

from acp.schema import SessionMode, SessionModeState


# ═══════════════════════════════════════════════════════════════════
# ACP mode definitions (surfaced to the client)
# ═══════════════════════════════════════════════════════════════════

DEFAULT_MODES = SessionModeState(
    current_mode_id="accept_edits",
    available_modes=[
        SessionMode(
            id="ask_before_edits",
            name="Ask Before Edits",
            description="Requires approval for file edits, writes, shell commands, and plans.",
        ),
        SessionMode(
            id="accept_edits",
            name="Accept Edits",
            description="Auto-approves file operations; asks before shell commands and plans.",
        ),
        SessionMode(
            id="accept_everything",
            name="Accept Everything",
            description="Auto-approves all operations without asking for permission.",
        ),
    ],
)


# ═══════════════════════════════════════════════════════════════════
# interrupt_on dicts for HumanInTheLoopMiddleware per mode
# ═══════════════════════════════════════════════════════════════════

# Each value is a dict[str, dict | bool]:
#   - dict  → tool requires HITL with the specified allowed_decisions
#   - False → explicitly no HITL for that tool
INTERRUPT_ON_BY_MODE: dict[str, dict[str, dict | bool]] = {
    "ask_before_edits": {
        "edit_file": {"allowed_decisions": ["approve", "edit", "reject"]},
        "write_file": {"allowed_decisions": ["approve", "edit", "reject"]},
        "write_todos": {"allowed_decisions": ["approve", "reject"]},
        "execute": {"allowed_decisions": ["approve", "edit", "reject"]},
        "read_file": False,
        "ls": False,
        "grep": False,
    },
    "accept_edits": {
        "write_todos": {"allowed_decisions": ["approve", "reject"]},
        "execute": {"allowed_decisions": ["approve", "edit", "reject"]},
        "edit_file": False,
        "write_file": False,
        "read_file": False,
        "ls": False,
        "grep": False,
    },
    "accept_everything": {},
}


def get_interrupt_on(mode_id: str) -> dict[str, dict | bool]:
    """Return the ``interrupt_on`` config for ``HumanInTheLoopMiddleware``.

    Falls back to the most restrictive mode if *mode_id* is unknown.
    """
    return INTERRUPT_ON_BY_MODE.get(mode_id, INTERRUPT_ON_BY_MODE["ask_before_edits"])
