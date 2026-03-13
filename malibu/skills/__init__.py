"""Malibu skills system — directory-based skill packages.

Skills are folders containing a SKILL.md file with YAML frontmatter
(name, description) and markdown instructions. Optional subdirectories:
scripts/, references/, assets/.

Public API::

    from malibu.skills import SkillRegistry, SkillMetadata, SkillLoader
"""

from malibu.skills.base import SkillMetadata, load_skill_from_path, parse_skill_frontmatter
from malibu.skills.loader import SkillLoader
from malibu.skills.registry import SkillRegistry

__all__ = [
    "SkillMetadata",
    "SkillLoader",
    "SkillRegistry",
    "load_skill_from_path",
    "parse_skill_frontmatter",
]
