"""Dangerous command detection for shell execution safety."""

from __future__ import annotations

import re
from dataclasses import dataclass

_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?/\b"), "Recursive delete from root filesystem"),
    (re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f|rm\s+-[a-zA-Z]*f[a-zA-Z]*r"), "Forced recursive delete"),
    (re.compile(r"\bsudo\b"), "Command uses sudo (elevated privileges)"),
    (re.compile(r"\bchmod\s+(-R\s+)?777\b"), "Sets world-writable permissions"),
    (re.compile(r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;"), "Fork bomb detected"),
    (re.compile(r"\bmv\s+/\b"), "Moving root filesystem path"),
    (re.compile(r"\bdd\s+.*\bif=.*\bof=/dev/"), "Raw disk write via dd"),
    (re.compile(r"\bcurl\b.*\|\s*\bbash\b"), "Piping remote script to bash"),
    (re.compile(r"\bwget\b.*\|\s*\bbash\b"), "Piping remote script to bash"),
    (re.compile(r"\bcurl\b.*\|\s*\bsh\b"), "Piping remote script to shell"),
    (re.compile(r"\bwget\b.*\|\s*\bsh\b"), "Piping remote script to shell"),
    (re.compile(r"\bmkfs\b"), "Filesystem format command"),
    (re.compile(r"\bfdisk\b"), "Disk partition command"),
    (
        re.compile(r"\bgit\s+push\s+.*--force\b.*\b(main|master|develop|production)\b"),
        "Force push to protected branch",
    ),
    (
        re.compile(r"\bgit\s+push\s+.*\b(main|master|develop|production)\b.*--force\b"),
        "Force push to protected branch",
    ),
]


@dataclass(frozen=True)
class CommandSafetyCheck:
    """Result of a command safety check."""

    is_dangerous: bool
    matched_pattern: str = ""
    risk_description: str = ""


def check_command(command: str) -> CommandSafetyCheck:
    """Check a shell command for dangerous patterns.

    Pure function with no side effects.

    Args:
        command: The shell command string to check.

    Returns:
        CommandSafetyCheck indicating whether the command is dangerous.
    """
    for pattern, description in _DANGEROUS_PATTERNS:
        if pattern.search(command):
            return CommandSafetyCheck(
                is_dangerous=True,
                matched_pattern=pattern.pattern,
                risk_description=description,
            )
    return CommandSafetyCheck(is_dangerous=False)
