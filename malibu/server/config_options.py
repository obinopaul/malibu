"""Config option handling for ACP set_config_option / ConfigOptionUpdate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from acp.schema import (
    SessionConfigOption,
    SessionConfigOptionSelect,
    SessionConfigSelectOption,
)


# Known config option IDs and their validators / display metadata
_CONFIG_SCHEMA: dict[str, dict[str, Any]] = {
    "temperature": {
        "type": float,
        "min": 0.0,
        "max": 2.0,
        "default": 0.7,
        "name": "Temperature",
        "description": "Controls randomness of LLM output",
        "options": ["0.0", "0.3", "0.5", "0.7", "1.0", "1.5", "2.0"],
    },
    "max_tokens": {
        "type": int,
        "min": 1,
        "max": 128_000,
        "default": 8192,
        "name": "Max Tokens",
        "description": "Maximum number of tokens in the response",
        "options": ["1024", "4096", "8192", "16384", "32768", "65536", "128000"],
    },
    "context_window": {
        "type": int,
        "min": 1024,
        "max": 200_000,
        "default": 128_000,
        "name": "Context Window",
        "description": "Maximum context window size",
        "options": ["8192", "32768", "65536", "128000", "200000"],
    },
    "auto_approve_reads": {
        "type": bool,
        "default": True,
        "name": "Auto-approve Reads",
        "description": "Automatically approve read operations",
        "options": ["true", "false"],
    },
}


@dataclass
class ConfigUpdateResult:
    """Result of setting a config option."""

    config_id: str
    value: Any


class ConfigOptionManager:
    """Track and validate per-session configuration options."""

    def __init__(self) -> None:
        self._session_config: dict[str, dict[str, Any]] = {}

    def get_config(self, session_id: str) -> dict[str, Any]:
        """Get the current config for a session."""
        return self._session_config.get(session_id, {})

    def set_option(self, session_id: str, config_id: str, value: str) -> ConfigUpdateResult | None:
        """Validate and set a config option, returning an update result."""
        schema = _CONFIG_SCHEMA.get(config_id)
        if schema is None:
            return None

        # Parse and validate
        try:
            parsed = schema["type"](value)
        except (ValueError, TypeError):
            return None

        if "min" in schema and parsed < schema["min"]:
            return None
        if "max" in schema and parsed > schema["max"]:
            return None

        if session_id not in self._session_config:
            self._session_config[session_id] = {}
        self._session_config[session_id][config_id] = parsed

        return ConfigUpdateResult(config_id=config_id, value=parsed)

    def build_session_config_options(self, session_id: str) -> list[SessionConfigOption]:
        """Build the full list of ACP SessionConfigOption objects for a session."""
        session_values = self._session_config.get(session_id, {})
        result: list[SessionConfigOption] = []
        for config_id, schema in _CONFIG_SCHEMA.items():
            current = session_values.get(config_id, schema["default"])
            options = [
                SessionConfigSelectOption(name=opt, value=opt)
                for opt in schema["options"]
            ]
            select = SessionConfigOptionSelect(
                id=config_id,
                name=schema["name"],
                type="select",
                current_value=str(current),
                options=options,
                description=schema.get("description"),
            )
            result.append(SessionConfigOption(root=select))
        return result

    def clear_session(self, session_id: str) -> None:
        self._session_config.pop(session_id, None)
