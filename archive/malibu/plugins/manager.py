"""Plugin manager — handles plugin discovery, installation, and management."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from malibu.plugins.models import (
    InstalledPlugin,
    InstalledPluginsRegistry,
    MarketplaceInfo,
    PluginMetadata,
)
from malibu.telemetry.logging import get_logger

log = get_logger(__name__)

# Default directories
_USER_PLUGINS_DIR = Path.home() / ".malibu" / "plugins"
_MARKETPLACES_DIR = Path.home() / ".malibu" / "plugins" / "marketplaces"
_REGISTRY_FILE = Path.home() / ".malibu" / "plugins.json"


class PluginManager:
    """Manages plugin lifecycle: discovery, installation, enabling/disabling."""

    def __init__(self, plugins_dir: Path | None = None) -> None:
        self._plugins_dir = plugins_dir or _USER_PLUGINS_DIR
        self._registry = self._load_registry()
        self._marketplaces: dict[str, MarketplaceInfo] = {}

    def _load_registry(self) -> InstalledPluginsRegistry:
        """Load the installed plugins registry from disk."""
        if not _REGISTRY_FILE.exists():
            return InstalledPluginsRegistry()

        try:
            data = json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
            registry = InstalledPluginsRegistry()
            for key, plugin_data in data.get("plugins", {}).items():
                registry.plugins[key] = InstalledPlugin(
                    name=plugin_data["name"],
                    marketplace=plugin_data["marketplace"],
                    version=plugin_data["version"],
                    path=plugin_data["path"],
                    scope=plugin_data.get("scope", "user"),
                    enabled=plugin_data.get("enabled", True),
                )
            return registry
        except Exception:
            log.exception("plugin_registry_load_failed")
            return InstalledPluginsRegistry()

    def _save_registry(self) -> None:
        """Save the installed plugins registry to disk."""
        _REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "plugins": {
                key: {
                    "name": p.name,
                    "marketplace": p.marketplace,
                    "version": p.version,
                    "path": p.path,
                    "scope": p.scope,
                    "enabled": p.enabled,
                }
                for key, p in self._registry.plugins.items()
            }
        }
        _REGISTRY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list_installed(self) -> list[InstalledPlugin]:
        """Return all installed plugins."""
        return self._registry.list_all()

    def list_enabled(self) -> list[InstalledPlugin]:
        """Return all enabled plugins."""
        return self._registry.list_enabled()

    def get_plugin(self, marketplace: str, name: str) -> InstalledPlugin | None:
        """Get an installed plugin by marketplace and name."""
        return self._registry.get(marketplace, name)

    def install_local(
        self,
        source_path: Path,
        scope: str = "user",
    ) -> InstalledPlugin:
        """Install a plugin from a local directory.

        Args:
            source_path: Path to the plugin directory (must have plugin.json).
            scope: "user" or "project".

        Returns:
            The installed plugin info.

        Raises:
            ValueError: If plugin.json is missing or invalid.
        """
        plugin_json = source_path / "plugin.json"
        if not plugin_json.exists():
            raise ValueError(f"No plugin.json found in {source_path}")

        try:
            metadata = PluginMetadata.from_dict(
                json.loads(plugin_json.read_text(encoding="utf-8"))
            )
        except Exception as exc:
            raise ValueError(f"Invalid plugin.json: {exc}")

        # Install to plugins directory
        dest = self._plugins_dir / metadata.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source_path, dest)

        plugin = InstalledPlugin(
            name=metadata.name,
            marketplace="local",
            version=metadata.version,
            path=str(dest),
            scope=scope,  # type: ignore[arg-type]
            enabled=True,
        )
        self._registry.add(plugin)
        self._save_registry()

        log.info("plugin_installed", name=metadata.name, version=metadata.version)
        return plugin

    def uninstall(self, marketplace: str, name: str) -> bool:
        """Uninstall a plugin.

        Args:
            marketplace: Source marketplace.
            name: Plugin name.

        Returns:
            True if uninstalled, False if not found.
        """
        plugin = self._registry.remove(marketplace, name)
        if plugin is None:
            return False

        # Remove plugin directory
        plugin_path = Path(plugin.path)
        if plugin_path.exists():
            shutil.rmtree(plugin_path)

        self._save_registry()
        log.info("plugin_uninstalled", name=name, marketplace=marketplace)
        return True

    def enable(self, marketplace: str, name: str) -> bool:
        """Enable a plugin."""
        plugin = self._registry.get(marketplace, name)
        if plugin is None:
            return False
        plugin.enabled = True
        self._save_registry()
        log.info("plugin_enabled", name=name)
        return True

    def disable(self, marketplace: str, name: str) -> bool:
        """Disable a plugin."""
        plugin = self._registry.get(marketplace, name)
        if plugin is None:
            return False
        plugin.enabled = False
        self._save_registry()
        log.info("plugin_disabled", name=name)
        return True

    def get_plugin_skills_dir(self, plugin: InstalledPlugin) -> Path | None:
        """Get the skills directory for a plugin."""
        plugin_path = Path(plugin.path)
        skills_dir = plugin_path / "skills"
        return skills_dir if skills_dir.is_dir() else plugin_path

    def get_plugin_skills(self, plugin: InstalledPlugin) -> list[Path]:
        """Return skill directories within a plugin.

        Scans for directories containing SKILL.md files.
        """
        skills_dir = self.get_plugin_skills_dir(plugin)
        if skills_dir is None or not skills_dir.exists():
            return []

        skill_paths: list[Path] = []
        # Check if the skills_dir itself is a skill
        if (skills_dir / "SKILL.md").exists():
            skill_paths.append(skills_dir)

        # Check subdirectories
        for child in skills_dir.iterdir():
            if child.is_dir() and (child / "SKILL.md").exists():
                skill_paths.append(child)

        return skill_paths

    # ── Marketplace operations ───────────────────────────────────

    def add_marketplace(self, name: str, url: str, branch: str = "main") -> MarketplaceInfo:
        """Register a marketplace.

        Args:
            name: Marketplace name.
            url: Git repository URL.
            branch: Branch to track.

        Returns:
            The registered MarketplaceInfo.
        """
        info = MarketplaceInfo(name=name, url=url, branch=branch)
        self._marketplaces[name] = info
        log.info("marketplace_added", name=name, url=url)
        return info

    def sync_marketplace(self, name: str) -> bool:
        """Clone or pull a marketplace repository.

        Args:
            name: Marketplace name (must be registered).

        Returns:
            True on success.
        """
        info = self._marketplaces.get(name)
        if info is None:
            return False

        dest = _MARKETPLACES_DIR / name
        try:
            if dest.exists() and (dest / ".git").exists():
                # Pull latest
                result = subprocess.run(
                    ["git", "pull"], cwd=str(dest),
                    capture_output=True, text=True, timeout=60,
                )
            else:
                # Clone
                dest.parent.mkdir(parents=True, exist_ok=True)
                result = subprocess.run(
                    ["git", "clone", "--branch", info.branch, "--single-branch", info.url, str(dest)],
                    capture_output=True, text=True, timeout=120,
                )

            if result.returncode != 0:
                log.warning("marketplace_sync_failed", name=name, stderr=result.stderr.strip())
                return False

            info.last_updated = datetime.now()
            log.info("marketplace_synced", name=name)
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            log.warning("marketplace_sync_error", name=name, error=str(exc))
            return False

    def list_marketplace_plugins(self, name: str) -> list[PluginMetadata]:
        """Scan a cloned marketplace for plugin.json files.

        Args:
            name: Marketplace name.

        Returns:
            List of plugin metadata found in the marketplace.
        """
        dest = _MARKETPLACES_DIR / name
        if not dest.exists():
            return []

        plugins: list[PluginMetadata] = []
        for plugin_json in dest.rglob("plugin.json"):
            try:
                data = json.loads(plugin_json.read_text(encoding="utf-8"))
                plugins.append(PluginMetadata.from_dict(data))
            except (OSError, json.JSONDecodeError):
                continue
        return plugins

    def install_from_marketplace(self, marketplace: str, plugin_name: str) -> InstalledPlugin | None:
        """Install a plugin from a synced marketplace.

        Args:
            marketplace: Marketplace name.
            plugin_name: Plugin name to install.

        Returns:
            InstalledPlugin or None if not found.
        """
        dest = _MARKETPLACES_DIR / marketplace
        if not dest.exists():
            return None

        for plugin_json in dest.rglob("plugin.json"):
            try:
                data = json.loads(plugin_json.read_text(encoding="utf-8"))
                if data.get("name") == plugin_name:
                    return self.install_local(plugin_json.parent, scope="user")
            except (OSError, json.JSONDecodeError):
                continue
        return None

    def install_from_url(self, url: str, name: str | None = None) -> InstalledPlugin | None:
        """Install a plugin by cloning from a git URL.

        Args:
            url: Git repository URL.
            name: Plugin name override.

        Returns:
            InstalledPlugin or None on failure.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            try:
                result = subprocess.run(
                    ["git", "clone", "--depth=1", url, tmp],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    log.warning("plugin_clone_failed", url=url, stderr=result.stderr.strip())
                    return None

                plugin_json = Path(tmp) / "plugin.json"
                if not plugin_json.exists():
                    log.warning("plugin_no_manifest", url=url)
                    return None

                return self.install_local(Path(tmp), scope="user")
            except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
                log.warning("plugin_install_from_url_failed", url=url, error=str(exc))
                return None
