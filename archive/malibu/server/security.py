"""Command security — signature extraction and allowlist management.

Adapts the DeepAgent extract_command_types pattern with per-session
allowlists backed by the database.
"""

from __future__ import annotations

import shlex


def extract_command_types(command: str) -> list[str]:
    """Extract command type signatures from a shell command string.

    Handles &&, ||, ; separators, and pipes.  For security-sensitive
    commands (python, node, npm, uv, etc.) the full sub-command signature
    is retained to avoid over-permissioning.

    Examples:
        >>> extract_command_types("npm install && npm test")
        ['npm install', 'npm test']
        >>> extract_command_types("python -m pytest tests/")
        ['python -m pytest']
        >>> extract_command_types("ls -la | grep foo")
        ['ls', 'grep']
    """
    if not command or not command.strip():
        return []

    # Split on &&, ||, ; first, then on pipes
    segments: list[str] = []
    for part in _split_on_operators(command):
        for pipe_part in part.split("|"):
            stripped = pipe_part.strip()
            if stripped:
                segments.append(stripped)

    result: list[str] = []
    for segment in segments:
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        if not tokens:
            continue
        sig = _extract_signature(tokens)
        if sig:
            result.append(sig)
    return result


def truncate_command_for_display(command: str, *, max_length: int = 80) -> str:
    """Truncate a command string for safe display in permission prompts."""
    if len(command) <= max_length:
        return command
    return command[: max_length - 3] + "..."


# ── Internal helpers ──────────────────────────────────────────────

_SENSITIVE_COMMANDS = {
    "python", "python3", "node", "npm", "yarn", "pnpm",
    "npx", "uv", "pip", "pip3", "cargo", "go",
}


def _split_on_operators(cmd: str) -> list[str]:
    """Split on &&, ||, ; while being mindful of quoting."""
    parts: list[str] = []
    current: list[str] = []
    i = 0
    in_single = False
    in_double = False
    while i < len(cmd):
        c = cmd[i]
        if c == "'" and not in_double:
            in_single = not in_single
            current.append(c)
        elif c == '"' and not in_single:
            in_double = not in_double
            current.append(c)
        elif not in_single and not in_double:
            if c == ";" or (c == "&" and i + 1 < len(cmd) and cmd[i + 1] == "&"):
                parts.append("".join(current))
                current = []
                if c == "&":
                    i += 1  # skip second &
            elif c == "|" and i + 1 < len(cmd) and cmd[i + 1] == "|":
                parts.append("".join(current))
                current = []
                i += 1  # skip second |
            else:
                current.append(c)
        else:
            current.append(c)
        i += 1
    if current:
        parts.append("".join(current))
    return parts


def _extract_signature(tokens: list[str]) -> str:
    """Extract the command signature from a list of shell tokens."""
    base = tokens[0].split("/")[-1]  # strip path prefix

    if base not in _SENSITIVE_COMMANDS:
        return base

    if base in ("python", "python3"):
        return _python_sig(base, tokens)
    if base == "node":
        return _node_sig(base, tokens)
    if base in ("npm", "yarn", "pnpm"):
        return _npm_sig(base, tokens)
    if base == "npx":
        return f"{base} {tokens[1]}" if len(tokens) > 1 else base
    if base == "uv":
        return _uv_sig(base, tokens)
    if base in ("pip", "pip3"):
        return f"{base} {tokens[1]}" if len(tokens) > 1 else base
    if base in ("cargo", "go"):
        return f"{base} {tokens[1]}" if len(tokens) > 1 else base
    return base


def _python_sig(base: str, tokens: list[str]) -> str:
    if len(tokens) < 2:
        return base
    if tokens[1] == "-m" and len(tokens) > 2:
        return f"{base} -m {tokens[2]}"
    if tokens[1] == "-c":
        return f"{base} -c"
    return base


def _node_sig(base: str, tokens: list[str]) -> str:
    if len(tokens) < 2:
        return base
    if tokens[1] in ("-e", "-p"):
        return f"{base} {tokens[1]}"
    return base


def _npm_sig(base: str, tokens: list[str]) -> str:
    if len(tokens) < 2:
        return base
    sub = tokens[1]
    if sub == "run" and len(tokens) > 2:
        return f"{base} run {tokens[2]}"
    return f"{base} {sub}"


def _uv_sig(base: str, tokens: list[str]) -> str:
    if len(tokens) < 2:
        return base
    sub = tokens[1]
    if sub == "run" and len(tokens) > 2:
        return f"{base} run {tokens[2]}"
    return f"{base} {sub}"
