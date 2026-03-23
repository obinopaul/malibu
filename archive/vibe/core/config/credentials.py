from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, set_key

from vibe.core.paths import GLOBAL_ENV_FILE


def _get_env_path(path: Path | None = None) -> Path:
    return path or GLOBAL_ENV_FILE.path


def read_global_env_values(path: Path | None = None) -> dict[str, str]:
    env_path = _get_env_path(path)
    if not env_path.is_file():
        return {}
    values = dotenv_values(env_path)
    return {
        key: value
        for key, value in values.items()
        if isinstance(key, str) and isinstance(value, str) and value
    }


def get_saved_api_key(env_key: str, path: Path | None = None) -> str | None:
    if value := os.getenv(env_key):
        return value
    return read_global_env_values(path).get(env_key)


def has_saved_api_key(env_key: str, path: Path | None = None) -> bool:
    return get_saved_api_key(env_key, path) is not None


def save_api_key(env_key: str, api_key: str, path: Path | None = None) -> None:
    env_path = _get_env_path(path)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    set_key(env_path, env_key, api_key)
    os.environ[env_key] = api_key


def mask_secret(value: str | None) -> str:
    if not value:
        return "Not set"
    if len(value) <= 8:
        return "Configured"
    return f"{value[:4]}...{value[-4:]}"
