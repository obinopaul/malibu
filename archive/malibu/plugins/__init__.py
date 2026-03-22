"""Plugin system for Malibu — extensible skill packages.

Plugins are collections of skills that can be installed from marketplaces
or local directories. Each plugin contains one or more SKILL.md-based skills.
"""

from malibu.plugins.models import (
    DirectPlugin,
    InstalledPlugin,
    MarketplaceInfo,
    PluginMetadata,
)
from malibu.plugins.manager import PluginManager

__all__ = [
    "DirectPlugin",
    "InstalledPlugin",
    "MarketplaceInfo",
    "PluginMetadata",
    "PluginManager",
]
