"""Load hooks configuration from global and project settings files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from malibu.hooks.models import HookConfig, VALID_EVENT_NAMES
from malibu.telemetry.logging import get_logger

_log = get_logger(__name__)


def _read_hooks_from_file(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Read hooks payload from settings JSON.

    Expected format:
        {
          "hooks": {
            "PreToolUse": [
              {"matcher": "run_.*", "hooks": [{"type": "command", "command": "..."}]}
            ]
          }
        }
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _log.warning("hooks_settings_read_failed", path=str(path))
        return {}

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return {}
    return hooks


def load_hooks_config(working_dir: Path | str | None = None) -> HookConfig:
    """Load and merge hooks config from user and project scopes.

    Merge order: global first, then project (project hooks appended for same event).

    Files:
      - ~/.malibu/settings.json
      - <working_dir>/.malibu/settings.json
    """
    wd = Path(working_dir) if working_dir else Path.cwd()

    global_settings = Path.home() / ".malibu" / "settings.json"
    project_settings = wd / ".malibu" / "settings.json"

    global_hooks = _read_hooks_from_file(global_settings)
    project_hooks = _read_hooks_from_file(project_settings)

    merged: dict[str, list[dict[str, Any]]] = {}
    all_events = set(global_hooks.keys()) | set(project_hooks.keys())

    for event_name in all_events:
        if event_name not in VALID_EVENT_NAMES:
            continue

        global_matchers = global_hooks.get(event_name, [])
        project_matchers = project_hooks.get(event_name, [])
        if not isinstance(global_matchers, list):
            global_matchers = []
        if not isinstance(project_matchers, list):
            project_matchers = []

        merged[event_name] = global_matchers + project_matchers

    return HookConfig.from_dict({"hooks": merged})
