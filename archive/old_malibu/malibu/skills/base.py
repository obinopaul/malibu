"""Skill data types for the Malibu skills system.

Skills are directory-based packages with a SKILL.md file containing
YAML frontmatter (name, description) and markdown instructions.
This module defines the TypedDict structures for skill metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict


class SkillMetadata(TypedDict, total=False):
    """Metadata parsed from a skill's SKILL.md frontmatter.

    Required fields:
        name: Unique identifier for the skill (lowercase with hyphens).
        description: Trigger description explaining when to invoke the skill.

    Optional fields:
        license: License identifier (e.g., "MIT").
        compatibility: Target platform/tool compatibility notes.
        allowed_tools: List of tool patterns the skill may use.
        metadata: Additional arbitrary key-value metadata.
        instructions: The markdown body content (loaded on demand).
        source: Origin of the skill ("built-in", "user", "project").
        path: Filesystem path to the skill directory.
    """

    # Required
    name: str
    description: str

    # Optional
    license: str | None
    compatibility: str | None
    allowed_tools: list[str] | None
    metadata: dict[str, Any] | None
    instructions: str | None
    source: str  # "built-in", "user", "project"
    path: Path | None


def parse_skill_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter and markdown body from SKILL.md content.

    Args:
        content: Full text of a SKILL.md file.

    Returns:
        Tuple of (frontmatter_dict, markdown_body).
        If no frontmatter is found, returns ({}, content).
    """
    import yaml

    content = content.strip()
    if not content.startswith("---"):
        return {}, content

    # Find closing ---
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return {}, content

    frontmatter_text = content[3:end_idx].strip()
    body = content[end_idx + 3 :].strip()

    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        frontmatter = {}

    return frontmatter, body


def load_skill_from_path(skill_dir: Path, source: str = "unknown") -> SkillMetadata | None:
    """Load skill metadata from a directory containing SKILL.md.

    Args:
        skill_dir: Path to the skill directory.
        source: Origin label ("built-in", "user", "project").

    Returns:
        SkillMetadata if valid SKILL.md found, else None.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None

    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None

    frontmatter, body = parse_skill_frontmatter(content)

    name = frontmatter.get("name")
    description = frontmatter.get("description")

    if not name or not description:
        return None

    return SkillMetadata(
        name=name,
        description=description,
        license=frontmatter.get("license"),
        compatibility=frontmatter.get("compatibility"),
        allowed_tools=frontmatter.get("allowed_tools"),
        metadata=frontmatter.get("metadata"),
        instructions=body,
        source=source,
        path=skill_dir,
    )
