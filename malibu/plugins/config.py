"""Configuration utilities for loading and saving plugin registry files.

Standalone implementation — no opendev imports.
All paths under ~/.malibu/ and <project>/.malibu/.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from malibu.plugins.models import InstalledPlugin, MarketplaceInfo

# ── Path definitions ────────────────────────────────────────────────
MALIBU_DIR = Path.home() / ".malibu"
MARKETPLACES_FILE = MALIBU_DIR / "marketplaces.json"
USER_PLUGINS_FILE = MALIBU_DIR / "plugins.json"
USER_BUNDLES_DIR = MALIBU_DIR / "plugins" / "bundles"
PROJECT_PLUGINS_FILE = Path(".malibu") / "plugins.json"


def _parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO datetime string, returning None on failure."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
    return None


# ── Marketplaces ────────────────────────────────────────────────────

def load_known_marketplaces() -> dict[str, MarketplaceInfo]:
    """Load the known marketplaces registry from ~/.malibu/marketplaces.json."""
    if not MARKETPLACES_FILE.exists():
        return {}
    try:
        data = json.loads(MARKETPLACES_FILE.read_text(encoding="utf-8"))
        result: dict[str, MarketplaceInfo] = {}
        for name, info in data.get("marketplaces", {}).items():
            result[name] = MarketplaceInfo(
                name=name,
                url=info.get("url", ""),
                branch=info.get("branch", "main"),
                added_at=_parse_datetime(info.get("added_at")) or datetime.now(),
                last_updated=_parse_datetime(info.get("last_updated")),
            )
        return result
    except (OSError, json.JSONDecodeError):
        return {}


def save_known_marketplaces(marketplaces: dict[str, MarketplaceInfo]) -> None:
    """Save the known marketplaces registry."""
    MARKETPLACES_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "marketplaces": {
            name: {
                "url": mp.url,
                "branch": mp.branch,
                "added_at": mp.added_at.isoformat() if mp.added_at else None,
                "last_updated": mp.last_updated.isoformat() if mp.last_updated else None,
            }
            for name, mp in marketplaces.items()
        }
    }
    MARKETPLACES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Installed plugins ──────────────────────────────────────────────

def _plugins_file(scope: str = "user", cwd: str | None = None) -> Path:
    """Resolve the plugins.json file path for a given scope."""
    if scope == "project" and cwd:
        return Path(cwd) / ".malibu" / "plugins.json"
    if scope == "project":
        return PROJECT_PLUGINS_FILE
    return USER_PLUGINS_FILE


def load_installed_plugins(scope: str = "user", cwd: str | None = None) -> dict[str, InstalledPlugin]:
    """Load installed plugins from the registry file.

    Args:
        scope: 'user' for global or 'project' for project-specific.
        cwd: Working directory for project scope resolution.

    Returns:
        Dict of registry_key -> InstalledPlugin.
    """
    path = _plugins_file(scope, cwd)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        result: dict[str, InstalledPlugin] = {}
        for key, plugin_data in data.get("plugins", {}).items():
            result[key] = InstalledPlugin(
                name=plugin_data.get("name", ""),
                marketplace=plugin_data.get("marketplace", "local"),
                version=plugin_data.get("version", "0.0.0"),
                path=plugin_data.get("path", ""),
                scope=plugin_data.get("scope", scope),
                enabled=plugin_data.get("enabled", True),
                installed_at=_parse_datetime(plugin_data.get("installed_at")) or datetime.now(),
            )
        return result
    except (OSError, json.JSONDecodeError):
        return {}


def save_installed_plugins(
    plugins: dict[str, InstalledPlugin],
    scope: str = "user",
    cwd: str | None = None,
) -> None:
    """Save installed plugins to the registry file."""
    path = _plugins_file(scope, cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "plugins": {
            key: {
                "name": p.name,
                "marketplace": p.marketplace,
                "version": p.version,
                "path": p.path,
                "scope": p.scope,
                "enabled": p.enabled,
                "installed_at": p.installed_at.isoformat() if p.installed_at else None,
            }
            for key, p in plugins.items()
        }
    }
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def get_all_installed_plugins(cwd: str | None = None) -> list[InstalledPlugin]:
    """Get all installed plugins from both user and project scopes.

    Project plugins have priority over user plugins with the same key.
    """
    plugins: list[InstalledPlugin] = []
    project_plugins = load_installed_plugins("project", cwd)
    plugins.extend(project_plugins.values())

    user_plugins = load_installed_plugins("user", cwd)
    project_keys = set(project_plugins.keys())
    for key, plugin in user_plugins.items():
        if key not in project_keys:
            plugins.append(plugin)

    return plugins


# ── Direct plugins (bundles) ───────────────────────────────────────

def _bundles_file(scope: str = "user", cwd: str | None = None) -> Path:
    """Resolve the bundles.json file path."""
    if scope == "project" and cwd:
        return Path(cwd) / ".malibu" / "bundles.json"
    if scope == "project":
        return Path(".malibu") / "bundles.json"
    return MALIBU_DIR / "bundles.json"


def load_direct_plugins(scope: str = "user", cwd: str | None = None) -> dict[str, dict[str, Any]]:
    """Load direct plugin bundles from the registry file."""
    path = _bundles_file(scope, cwd)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("bundles", {})
    except (OSError, json.JSONDecodeError):
        return {}


def save_direct_plugins(
    bundles: dict[str, dict[str, Any]],
    scope: str = "user",
    cwd: str | None = None,
) -> None:
    """Save direct plugin bundles to the registry file."""
    path = _bundles_file(scope, cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"bundles": bundles}
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
