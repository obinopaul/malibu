"""Built-in skills shipped with Malibu.

Built-in skills are directory-based packages stored in this folder.
Each skill directory contains a SKILL.md file with YAML frontmatter
and markdown instructions.

Discovery is handled by malibu.skills.loader.SkillLoader.
"""

from pathlib import Path

BUILTIN_SKILLS_DIR = Path(__file__).parent

__all__ = ["BUILTIN_SKILLS_DIR"]
