from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import shutil

from vibe import VIBE_ROOT


class GlobalPath:
    def __init__(self, resolver: Callable[[], Path]) -> None:
        self._resolver = resolver

    @property
    def path(self) -> Path:
        return self._resolver()


_DEFAULT_VIBE_HOME = Path.home() / ".vibe"
_DEFAULT_MALIBU_HOME = Path.home() / ".malibu"


def _copy_legacy_home(src: Path, dst: Path) -> None:
    if dst.exists() or not src.is_dir():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(src, dst, dirs_exist_ok=False)
    except OSError:
        return


def _resolve_home_path() -> Path:
    if malibu_home := os.getenv("MALIBU_HOME"):
        return Path(malibu_home).expanduser().resolve()
    if vibe_home := os.getenv("VIBE_HOME"):
        return Path(vibe_home).expanduser().resolve()

    default_malibu = _DEFAULT_MALIBU_HOME.expanduser().resolve()
    default_vibe = _DEFAULT_VIBE_HOME.expanduser().resolve()

    if default_malibu.exists():
        return default_malibu

    if default_vibe.exists():
        _copy_legacy_home(default_vibe, default_malibu)
        return default_malibu

    return default_malibu


def _get_vibe_home() -> Path:
    return _resolve_home_path()


MALIBU_HOME = GlobalPath(_resolve_home_path)
VIBE_HOME = GlobalPath(_get_vibe_home)
GLOBAL_ENV_FILE = GlobalPath(lambda: MALIBU_HOME.path / ".env")
SESSION_LOG_DIR = GlobalPath(lambda: MALIBU_HOME.path / "logs" / "session")
TRUSTED_FOLDERS_FILE = GlobalPath(lambda: MALIBU_HOME.path / "trusted_folders.toml")
LOG_DIR = GlobalPath(lambda: MALIBU_HOME.path / "logs")
LOG_FILE = GlobalPath(lambda: MALIBU_HOME.path / "logs" / "malibu.log")
HISTORY_FILE = GlobalPath(lambda: MALIBU_HOME.path / "malibuhistory")
PLANS_DIR = GlobalPath(lambda: MALIBU_HOME.path / "plans")

DEFAULT_TOOL_DIR = GlobalPath(lambda: VIBE_ROOT / "core" / "tools" / "builtins")
BUILTIN_SKILLS_DIR = GlobalPath(lambda: VIBE_ROOT / "core" / "skills" / "builtins")
