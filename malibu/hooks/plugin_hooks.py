"""In-process Python plugin hooks for pre/post tool interception."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Protocol

from malibu.telemetry.logging import get_logger

_log = get_logger(__name__)


class PluginHook(Protocol):
    """Protocol for in-process plugin hooks."""

    def on_pre_tool_use(
        self,
        tool_name: str,
        args: dict[str, Any],
    ) -> dict[str, Any] | None:
        ...

    def on_post_tool_use(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        ...


class PluginHookManager:
    """Discover and execute in-process plugin hook modules.

    Discovery paths:
      - ~/.malibu/plugins/*.py
      - <working_dir>/.malibu/plugins/*.py
    """

    def __init__(self, working_dir: str | None = None) -> None:
        self._working_dir = Path(working_dir) if working_dir else Path.cwd()
        self._hooks: list[PluginHook] = []
        self._loaded: set[str] = set()

    def discover_and_load(self) -> int:
        plugin_dirs = [
            Path.home() / ".malibu" / "plugins",
            self._working_dir / ".malibu" / "plugins",
        ]

        loaded_count = 0
        for plugin_dir in plugin_dirs:
            if not plugin_dir.exists():
                continue
            for plugin_file in sorted(plugin_dir.glob("*.py")):
                if plugin_file.name.startswith("_"):
                    continue
                loaded_count += self._load_plugin(plugin_file)

        if loaded_count:
            _log.info("plugin_hooks_loaded", count=loaded_count)
        return loaded_count

    def _load_plugin(self, plugin_path: Path) -> int:
        module_id = str(plugin_path.resolve())
        if module_id in self._loaded:
            return 0

        try:
            spec = importlib.util.spec_from_file_location(
                f"malibu_plugin_{plugin_path.stem}", plugin_path
            )
            if spec is None or spec.loader is None:
                return 0

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            register_fn = getattr(module, "register", None)
            if register_fn is None:
                _log.warning("plugin_missing_register", plugin=str(plugin_path))
                return 0

            hooks = register_fn()
            if not isinstance(hooks, (list, tuple)):
                hooks = [hooks]

            count = 0
            for hook in hooks:
                if hasattr(hook, "on_pre_tool_use") or hasattr(hook, "on_post_tool_use"):
                    self._hooks.append(hook)
                    count += 1
            self._loaded.add(module_id)
            return count
        except Exception as exc:
            _log.warning("plugin_load_failed", plugin=str(plugin_path), error=str(exc))
            return 0

    def run_pre_hooks(
        self,
        tool_name: str,
        args: dict[str, Any],
    ) -> tuple[dict[str, Any], bool, str]:
        current_args = args
        for hook in self._hooks:
            if not hasattr(hook, "on_pre_tool_use"):
                continue
            try:
                result = hook.on_pre_tool_use(tool_name, current_args)
                if result is None:
                    continue
                if result.get("blocked"):
                    return current_args, False, str(result.get("reason", "Blocked by plugin"))
                if "args" in result and isinstance(result["args"], dict):
                    current_args = result["args"]
            except Exception as exc:
                _log.warning("plugin_pre_hook_failed", hook=type(hook).__name__, error=str(exc))
        return current_args, True, ""

    def run_post_hooks(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        current_result = result
        for hook in self._hooks:
            if not hasattr(hook, "on_post_tool_use"):
                continue
            try:
                updated = hook.on_post_tool_use(tool_name, args, current_result)
                if isinstance(updated, dict):
                    current_result = updated
            except Exception as exc:
                _log.warning("plugin_post_hook_failed", hook=type(hook).__name__, error=str(exc))
        return current_result

    @property
    def hook_count(self) -> int:
        return len(self._hooks)

    def clear(self) -> None:
        self._hooks.clear()
        self._loaded.clear()
