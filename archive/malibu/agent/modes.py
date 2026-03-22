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
            id="plan",
            name="Plan Mode",
            description="Agent reasons and plans but all tools require approval.",
        ),
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
    "plan": {
        "edit_file": {"allowed_decisions": ["approve", "reject"]},
        "write_file": {"allowed_decisions": ["approve", "reject"]},
        "apply_patch": {"allowed_decisions": ["approve", "reject"]},
        "str_replace": {"allowed_decisions": ["approve", "reject"]},
        "write_todos": {"allowed_decisions": ["approve", "reject"]},
        "execute": {"allowed_decisions": ["approve", "reject"]},
        "shell_init": {"allowed_decisions": ["approve", "reject"]},
        "shell_run": {"allowed_decisions": ["approve", "reject"]},
        "shell_view": {"allowed_decisions": ["approve", "reject"]},
        "shell_list": {"allowed_decisions": ["approve", "reject"]},
        "shell_write": {"allowed_decisions": ["approve", "reject"]},
        "shell_stop": {"allowed_decisions": ["approve", "reject"]},
        "read_file": {"allowed_decisions": ["approve", "reject"]},
        "ls": {"allowed_decisions": ["approve", "reject"]},
        "grep": {"allowed_decisions": ["approve", "reject"]},
        "ast_grep": {"allowed_decisions": ["approve", "reject"]},
        "lsp": {"allowed_decisions": ["approve", "reject"]},
        "web_search": {"allowed_decisions": ["approve", "reject"]},
        "web_batch_search": {"allowed_decisions": ["approve", "reject"]},
        "web_visit": {"allowed_decisions": ["approve", "reject"]},
        "web_visit_compress": {"allowed_decisions": ["approve", "reject"]},
        "image_search": {"allowed_decisions": ["approve", "reject"]},
        "read_remote_image": {"allowed_decisions": ["approve", "reject"]},
        "generate_image": {"allowed_decisions": ["approve", "reject"]},
        "generate_video": {"allowed_decisions": ["approve", "reject"]},
        "git_status": {"allowed_decisions": ["approve", "reject"]},
        "git_diff": {"allowed_decisions": ["approve", "reject"]},
        "git_log": {"allowed_decisions": ["approve", "reject"]},
        "git_commit": {"allowed_decisions": ["approve", "reject"]},
        "git_worktree_create": {"allowed_decisions": ["approve", "reject"]},
        "git_worktree_list": {"allowed_decisions": ["approve", "reject"]},
        "git_worktree_remove": {"allowed_decisions": ["approve", "reject"]},
    },
    "ask_before_edits": {
        "edit_file": {"allowed_decisions": ["approve", "edit", "reject"]},
        "write_file": {"allowed_decisions": ["approve", "edit", "reject"]},
        "apply_patch": {"allowed_decisions": ["approve", "edit", "reject"]},
        "str_replace": {"allowed_decisions": ["approve", "edit", "reject"]},
        "write_todos": {"allowed_decisions": ["approve", "reject"]},
        "execute": {"allowed_decisions": ["approve", "edit", "reject"]},
        "shell_init": {"allowed_decisions": ["approve", "edit", "reject"]},
        "shell_run": {"allowed_decisions": ["approve", "edit", "reject"]},
        "shell_write": {"allowed_decisions": ["approve", "edit", "reject"]},
        "shell_stop": {"allowed_decisions": ["approve", "edit", "reject"]},
        "read_file": False,
        "ls": False,
        "grep": False,
        "ast_grep": False,
        "lsp": False,
        "shell_view": False,
        "shell_list": False,
        "web_search": False,
        "web_batch_search": False,
        "web_visit": False,
        "web_visit_compress": False,
        "image_search": False,
        "read_remote_image": False,
        "generate_image": {"allowed_decisions": ["approve", "edit", "reject"]},
        "generate_video": {"allowed_decisions": ["approve", "edit", "reject"]},
        "git_status": False,
        "git_diff": False,
        "git_log": False,
        "git_worktree_list": False,
        "git_commit": {"allowed_decisions": ["approve", "reject"]},
        "git_worktree_create": {"allowed_decisions": ["approve", "reject"]},
        "git_worktree_remove": {"allowed_decisions": ["approve", "reject"]},
    },
    "accept_edits": {
        "write_todos": {"allowed_decisions": ["approve", "reject"]},
        "execute": {"allowed_decisions": ["approve", "edit", "reject"]},
        "shell_init": {"allowed_decisions": ["approve", "edit", "reject"]},
        "shell_run": {"allowed_decisions": ["approve", "edit", "reject"]},
        "shell_write": {"allowed_decisions": ["approve", "edit", "reject"]},
        "shell_stop": {"allowed_decisions": ["approve", "edit", "reject"]},
        "edit_file": False,
        "write_file": False,
        "apply_patch": False,
        "str_replace": False,
        "read_file": False,
        "ls": False,
        "grep": False,
        "ast_grep": False,
        "lsp": False,
        "shell_view": False,
        "shell_list": False,
        "web_search": False,
        "web_batch_search": False,
        "web_visit": False,
        "web_visit_compress": False,
        "image_search": False,
        "read_remote_image": False,
        "generate_image": False,
        "generate_video": False,
        "git_status": False,
        "git_diff": False,
        "git_log": False,
        "git_worktree_list": False,
        "git_commit": {"allowed_decisions": ["approve", "reject"]},
        "git_worktree_create": {"allowed_decisions": ["approve", "reject"]},
        "git_worktree_remove": {"allowed_decisions": ["approve", "reject"]},
    },
    "accept_everything": {},
}


def get_interrupt_on(mode_id: str) -> dict[str, dict | bool]:
    """Return the ``interrupt_on`` config for ``HumanInTheLoopMiddleware``.

    Falls back to the most restrictive mode if *mode_id* is unknown.
    """
    return INTERRUPT_ON_BY_MODE.get(mode_id, INTERRUPT_ON_BY_MODE["ask_before_edits"])
