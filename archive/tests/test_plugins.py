"""Tests for malibu.plugins — manager, config, models, and skill discovery."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from malibu.plugins.models import (
    DirectPlugin,
    InstalledPlugin,
    InstalledPluginsRegistry,
    MarketplaceInfo,
    PluginMetadata,
)
from malibu.plugins.manager import PluginManager
from malibu.plugins.config import (
    load_installed_plugins,
    save_installed_plugins,
    load_known_marketplaces,
    save_known_marketplaces,
    get_all_installed_plugins,
    load_direct_plugins,
    save_direct_plugins,
)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def plugins_dir(tmp_path: Path, monkeypatch):
    """Temp directory for plugin installations with isolated registry."""
    d = tmp_path / "plugins"
    d.mkdir()
    # Isolate the registry file so tests don't leak state via ~/.malibu/plugins.json
    registry = tmp_path / "plugins_registry.json"
    monkeypatch.setattr("malibu.plugins.manager._REGISTRY_FILE", registry)
    return d


@pytest.fixture
def sample_plugin(tmp_path: Path):
    """Create a minimal sample plugin directory with plugin.json."""
    plugin_dir = tmp_path / "sample-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(json.dumps({
        "name": "sample-plugin",
        "version": "1.0.0",
        "description": "A sample plugin for testing",
        "author": "test",
        "skills": ["code_review"],
    }), encoding="utf-8")
    # Create a skill within the plugin
    skill_dir = plugin_dir / "skills" / "code_review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: code_review\ndescription: Code review skill\n---\nReview code.",
        encoding="utf-8",
    )
    return plugin_dir


@pytest.fixture
def sample_plugin_no_skills(tmp_path: Path):
    """Plugin without SKILL.md files."""
    plugin_dir = tmp_path / "no-skills-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(json.dumps({
        "name": "no-skills-plugin",
        "version": "0.1.0",
        "description": "Plugin without skills",
    }), encoding="utf-8")
    return plugin_dir


# ═══════════════════════════════════════════════════════════════════
# Plugin metadata
# ═══════════════════════════════════════════════════════════════════

class TestPluginMetadata:
    def test_from_dict(self) -> None:
        data = {
            "name": "my-plugin",
            "version": "2.0.0",
            "description": "A test plugin",
            "author": "author",
            "skills": ["skill1", "skill2"],
            "repository": "https://github.com/test/plugin",
            "license": "MIT",
        }
        meta = PluginMetadata.from_dict(data)
        assert meta.name == "my-plugin"
        assert meta.version == "2.0.0"
        assert meta.skills == ["skill1", "skill2"]
        assert meta.license == "MIT"

    def test_from_dict_defaults(self) -> None:
        meta = PluginMetadata.from_dict({})
        assert meta.name == ""
        assert meta.version == "0.0.0"
        assert meta.skills == []


class TestDirectPlugin:
    def test_creation(self) -> None:
        dp = DirectPlugin(name="test", url="https://example.com", path="/tmp/test")
        assert dp.name == "test"
        assert dp.branch == "main"
        assert dp.enabled is True
        assert isinstance(dp.installed_at, datetime)


# ═══════════════════════════════════════════════════════════════════
# Plugin registry
# ═══════════════════════════════════════════════════════════════════

class TestInstalledPluginsRegistry:
    def test_add_and_get(self) -> None:
        registry = InstalledPluginsRegistry()
        plugin = InstalledPlugin(
            name="test", marketplace="local", version="1.0", path="/tmp/test",
        )
        registry.add(plugin)
        assert registry.get("local", "test") is not None
        assert registry.get("local", "test").name == "test"

    def test_remove(self) -> None:
        registry = InstalledPluginsRegistry()
        plugin = InstalledPlugin(
            name="test", marketplace="local", version="1.0", path="/tmp/test",
        )
        registry.add(plugin)
        removed = registry.remove("local", "test")
        assert removed is not None
        assert registry.get("local", "test") is None

    def test_remove_nonexistent(self) -> None:
        registry = InstalledPluginsRegistry()
        assert registry.remove("local", "nope") is None

    def test_list_all(self) -> None:
        registry = InstalledPluginsRegistry()
        for i in range(3):
            registry.add(InstalledPlugin(
                name=f"p{i}", marketplace="local", version="1.0", path=f"/tmp/p{i}",
            ))
        assert len(registry.list_all()) == 3

    def test_list_enabled(self) -> None:
        registry = InstalledPluginsRegistry()
        registry.add(InstalledPlugin(
            name="a", marketplace="local", version="1.0", path="/tmp/a", enabled=True,
        ))
        registry.add(InstalledPlugin(
            name="b", marketplace="local", version="1.0", path="/tmp/b", enabled=False,
        ))
        enabled = registry.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].name == "a"


# ═══════════════════════════════════════════════════════════════════
# Plugin manager
# ═══════════════════════════════════════════════════════════════════

class TestPluginManager:
    def test_install_local(self, plugins_dir: Path, sample_plugin: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        plugin = mgr.install_local(sample_plugin)
        assert plugin.name == "sample-plugin"
        assert plugin.version == "1.0.0"
        assert plugin.marketplace == "local"
        assert plugin.enabled is True
        # Files should be copied to plugins_dir
        assert (plugins_dir / "sample-plugin" / "plugin.json").exists()

    def test_install_local_missing_json(self, plugins_dir: Path, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        mgr = PluginManager(plugins_dir=plugins_dir)
        with pytest.raises(ValueError, match="No plugin.json"):
            mgr.install_local(empty_dir)

    def test_install_local_invalid_json(self, plugins_dir: Path, tmp_path: Path) -> None:
        bad_dir = tmp_path / "bad"
        bad_dir.mkdir()
        (bad_dir / "plugin.json").write_text("not valid json", encoding="utf-8")
        mgr = PluginManager(plugins_dir=plugins_dir)
        with pytest.raises(ValueError, match="Invalid plugin.json"):
            mgr.install_local(bad_dir)

    def test_uninstall(self, plugins_dir: Path, sample_plugin: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        mgr.install_local(sample_plugin)
        assert mgr.uninstall("local", "sample-plugin") is True
        assert mgr.get_plugin("local", "sample-plugin") is None

    def test_uninstall_nonexistent(self, plugins_dir: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        assert mgr.uninstall("local", "nope") is False

    def test_enable_disable(self, plugins_dir: Path, sample_plugin: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        mgr.install_local(sample_plugin)
        assert mgr.disable("local", "sample-plugin") is True
        plugin = mgr.get_plugin("local", "sample-plugin")
        assert plugin.enabled is False

        assert mgr.enable("local", "sample-plugin") is True
        plugin = mgr.get_plugin("local", "sample-plugin")
        assert plugin.enabled is True

    def test_list_installed(self, plugins_dir: Path, sample_plugin: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        mgr.install_local(sample_plugin)
        installed = mgr.list_installed()
        assert len(installed) == 1
        assert installed[0].name == "sample-plugin"

    def test_list_enabled(self, plugins_dir: Path, sample_plugin: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        mgr.install_local(sample_plugin)
        mgr.disable("local", "sample-plugin")
        assert len(mgr.list_enabled()) == 0
        mgr.enable("local", "sample-plugin")
        assert len(mgr.list_enabled()) == 1

    def test_reinstall_overwrites(self, plugins_dir: Path, sample_plugin: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        mgr.install_local(sample_plugin)
        # Modify version
        plugin_json = sample_plugin / "plugin.json"
        data = json.loads(plugin_json.read_text())
        data["version"] = "2.0.0"
        plugin_json.write_text(json.dumps(data))
        # Re-install
        plugin = mgr.install_local(sample_plugin)
        assert plugin.version == "2.0.0"


# ═══════════════════════════════════════════════════════════════════
# Plugin skill discovery
# ═══════════════════════════════════════════════════════════════════

class TestPluginSkills:
    def test_get_plugin_skills(self, plugins_dir: Path, sample_plugin: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        plugin = mgr.install_local(sample_plugin)
        skills = mgr.get_plugin_skills(plugin)
        assert len(skills) == 1
        assert skills[0].name == "code_review"

    def test_get_plugin_skills_none(self, plugins_dir: Path, sample_plugin_no_skills: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        plugin = mgr.install_local(sample_plugin_no_skills)
        skills = mgr.get_plugin_skills(plugin)
        assert len(skills) == 0

    def test_get_plugin_skills_dir(self, plugins_dir: Path, sample_plugin: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        plugin = mgr.install_local(sample_plugin)
        skills_dir = mgr.get_plugin_skills_dir(plugin)
        assert skills_dir is not None
        assert skills_dir.name == "skills"

    def test_get_plugin_skills_dir_no_skills_subdir(self, plugins_dir: Path, sample_plugin_no_skills: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        plugin = mgr.install_local(sample_plugin_no_skills)
        skills_dir = mgr.get_plugin_skills_dir(plugin)
        # Falls back to the plugin dir itself
        assert skills_dir is not None


# ═══════════════════════════════════════════════════════════════════
# Plugin config round-trip
# ═══════════════════════════════════════════════════════════════════

class TestPluginConfig:
    def test_save_and_load_installed_plugins(self, tmp_path: Path, monkeypatch) -> None:
        registry_file = tmp_path / ".malibu" / "plugins.json"
        monkeypatch.setattr("malibu.plugins.config.USER_PLUGINS_FILE", registry_file)

        plugins = {
            "local:test-plugin": InstalledPlugin(
                name="test-plugin", marketplace="local", version="1.0.0",
                path="/tmp/test-plugin", scope="user", enabled=True,
            ),
        }
        save_installed_plugins(plugins, "user")
        loaded = load_installed_plugins("user")
        assert "local:test-plugin" in loaded
        assert loaded["local:test-plugin"].name == "test-plugin"
        assert loaded["local:test-plugin"].version == "1.0.0"

    def test_load_missing_file(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "malibu.plugins.config.USER_PLUGINS_FILE",
            tmp_path / "nonexistent.json",
        )
        assert load_installed_plugins("user") == {}

    def test_save_and_load_marketplaces(self, tmp_path: Path, monkeypatch) -> None:
        mp_file = tmp_path / ".malibu" / "marketplaces.json"
        monkeypatch.setattr("malibu.plugins.config.MARKETPLACES_FILE", mp_file)

        marketplaces = {
            "community": MarketplaceInfo(
                name="community",
                url="https://github.com/malibu-plugins/community",
                branch="main",
            ),
        }
        save_known_marketplaces(marketplaces)
        loaded = load_known_marketplaces()
        assert "community" in loaded
        assert loaded["community"].url == "https://github.com/malibu-plugins/community"

    def test_save_and_load_direct_plugins(self, tmp_path: Path, monkeypatch) -> None:
        bundles_file = tmp_path / ".malibu" / "bundles.json"
        monkeypatch.setattr("malibu.plugins.config.MALIBU_DIR", tmp_path / ".malibu")

        bundles = {
            "my-bundle": {
                "name": "my-bundle",
                "url": "https://github.com/test/bundle",
                "branch": "main",
            },
        }
        save_direct_plugins(bundles, "user")
        loaded = load_direct_plugins("user")
        assert "my-bundle" in loaded


# ═══════════════════════════════════════════════════════════════════
# Marketplace operations
# ═══════════════════════════════════════════════════════════════════

class TestMarketplace:
    def test_add_marketplace(self, plugins_dir: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        info = mgr.add_marketplace("community", "https://github.com/test/plugins", branch="main")
        assert info.name == "community"
        assert info.url == "https://github.com/test/plugins"

    def test_list_marketplace_plugins_empty(self, plugins_dir: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        plugins = mgr.list_marketplace_plugins("nonexistent")
        assert plugins == []

    def test_sync_unregistered_marketplace(self, plugins_dir: Path) -> None:
        mgr = PluginManager(plugins_dir=plugins_dir)
        assert mgr.sync_marketplace("nonexistent") is False
