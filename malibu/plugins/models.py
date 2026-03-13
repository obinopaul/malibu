"""Data models for the plugin/marketplace system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


@dataclass
class MarketplaceInfo:
    """Information about a registered marketplace."""

    name: str
    url: str
    branch: str = "main"
    added_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime | None = None


@dataclass
class PluginMetadata:
    """Metadata for a plugin from its plugin.json file."""

    name: str
    version: str
    description: str = ""
    author: str | None = None
    skills: list[str] = field(default_factory=list)
    repository: str | None = None
    license: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginMetadata":
        """Create PluginMetadata from a dictionary."""
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            author=data.get("author"),
            skills=data.get("skills", []),
            repository=data.get("repository"),
            license=data.get("license"),
        )


@dataclass
class InstalledPlugin:
    """Information about an installed plugin."""

    name: str
    marketplace: str
    version: str
    path: str
    scope: Literal["user", "project"] = "user"
    enabled: bool = True
    installed_at: datetime = field(default_factory=datetime.now)


@dataclass
class DirectPlugin:
    """A plugin installed directly from a URL or local path."""

    name: str
    url: str
    path: str
    branch: str = "main"
    enabled: bool = True
    installed_at: datetime = field(default_factory=datetime.now)


@dataclass
class InstalledPluginsRegistry:
    """Registry of installed plugins."""

    plugins: dict[str, InstalledPlugin] = field(default_factory=dict)

    @staticmethod
    def get_key(marketplace: str, plugin: str) -> str:
        """Generate registry key for a plugin."""
        return f"{marketplace}:{plugin}"

    def add(self, plugin: InstalledPlugin) -> None:
        """Add a plugin to the registry."""
        key = self.get_key(plugin.marketplace, plugin.name)
        self.plugins[key] = plugin

    def remove(self, marketplace: str, plugin: str) -> InstalledPlugin | None:
        """Remove a plugin from the registry."""
        key = self.get_key(marketplace, plugin)
        return self.plugins.pop(key, None)

    def get(self, marketplace: str, plugin: str) -> InstalledPlugin | None:
        """Get a plugin from the registry."""
        key = self.get_key(marketplace, plugin)
        return self.plugins.get(key)

    def list_all(self) -> list[InstalledPlugin]:
        """Return all installed plugins."""
        return list(self.plugins.values())

    def list_enabled(self) -> list[InstalledPlugin]:
        """Return all enabled plugins."""
        return [p for p in self.plugins.values() if p.enabled]
