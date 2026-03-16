"""Hierarchical JSON configuration loading from ~/.malibu/ and project .malibu/."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def _strip_json_comments(text: str) -> str:
    """Strip // and /* */ comments from JSON text.

    Preserves strings containing // or /* by tracking quote state.
    """
    result: list[str] = []
    i = 0
    in_string = False
    length = len(text)

    while i < length:
        ch = text[i]

        # Track string boundaries
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
            result.append(ch)
            i += 1
            continue

        if in_string:
            result.append(ch)
            i += 1
            continue

        # Line comment
        if ch == "/" and i + 1 < length and text[i + 1] == "/":
            while i < length and text[i] != "\n":
                i += 1
            continue

        # Block comment
        if ch == "/" and i + 1 < length and text[i + 1] == "*":
            i += 2
            while i + 1 < length and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2  # skip */
            continue

        result.append(ch)
        i += 1

    return "".join(result)


_VAR_RE = re.compile(r"\{(env|file):([^}]+)\}")


def _substitute_variables(value: Any) -> Any:
    """Substitute {env:VAR} and {file:path} references in string values.

    Recurses into dicts and lists.
    """
    if isinstance(value, str):
        def _replace(m: re.Match[str]) -> str:
            kind, ref = m.group(1), m.group(2)
            if kind == "env":
                return os.environ.get(ref, "")
            if kind == "file":
                try:
                    return Path(ref).expanduser().read_text(encoding="utf-8").strip()
                except OSError:
                    return ""
            return m.group(0)

        return _VAR_RE.sub(_replace, value)

    if isinstance(value, dict):
        return {k: _substitute_variables(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_variables(item) for item in value]
    return value


def _load_json_file(path: Path) -> dict[str, Any]:
    """Load a JSON file with comment stripping."""
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        stripped = _strip_json_comments(text)
        return json.loads(stripped)
    except (OSError, json.JSONDecodeError):
        return {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge override into base. Override wins for non-dict values."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_merged_config(cwd: str) -> dict[str, Any]:
    """Load and merge configuration from user and project scopes.

    Load order: ~/.malibu/settings.json (user) then <cwd>/.malibu/settings.json (project).
    Project values override user values. Variable substitution applied last.

    Args:
        cwd: Current working directory for project-level config.

    Returns:
        Merged configuration dict.
    """
    user_config = _load_json_file(Path.home() / ".malibu" / "settings.json")
    project_config = _load_json_file(Path(cwd) / ".malibu" / "settings.json")

    merged = _deep_merge(user_config, project_config)
    return _substitute_variables(merged)
