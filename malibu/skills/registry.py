"""Skill registry — aggregates skill metadata and instructions.

The registry is the single entry-point for managing loaded skills and
providing skill metadata to the agent for invocation decisions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from malibu.skills.base import SkillMetadata
from malibu.telemetry.logging import get_logger

log = get_logger(__name__)


class SkillRegistry:
    """Manages the lifecycle and aggregation of loaded skills."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillMetadata] = {}
        self._disabled: set[str] = set()

    # ── registration ──────────────────────────────────────────────

    def register(self, skill: SkillMetadata) -> None:
        """Register a skill (replaces any existing skill with the same name)."""
        name = skill["name"]
        self._skills[name] = skill
        self._disabled.discard(name)
        log.info("skill_registered", name=name, source=skill.get("source", "unknown"))

    def register_all(self, skills: list[SkillMetadata]) -> None:
        """Register multiple skills at once."""
        for skill in skills:
            self.register(skill)

    # ── enable / disable / reload ─────────────────────────────────

    def enable(self, name: str) -> None:
        """Enable a previously disabled skill."""
        if name not in self._skills:
            raise KeyError(f"Unknown skill: {name!r}")
        self._disabled.discard(name)
        log.info("skill_enabled", name=name)

    def disable(self, name: str) -> None:
        """Disable a skill so it won't be available to the agent."""
        if name not in self._skills:
            raise KeyError(f"Unknown skill: {name!r}")
        self._disabled.add(name)
        log.info("skill_disabled", name=name)

    def reload(self, name: str, skill: SkillMetadata) -> None:
        """Replace a skill with a new version (e.g. after hot-reload)."""
        was_disabled = name in self._disabled
        self._skills[name] = skill
        if was_disabled:
            self._disabled.add(name)
        log.info("skill_reloaded", name=name)

    # ── queries ───────────────────────────────────────────────────

    def _active_skills(self) -> list[SkillMetadata]:
        """Return skills that are registered and not disabled."""
        return [s for n, s in self._skills.items() if n not in self._disabled]

    def get_skill(self, name: str) -> SkillMetadata | None:
        """Get a specific skill by name."""
        return self._skills.get(name)

    def get_skill_instructions(self, name: str) -> str | None:
        """Get the markdown instructions for a specific skill."""
        skill = self._skills.get(name)
        if skill is None or name in self._disabled:
            return None
        return skill.get("instructions")

    def get_skills_manifest(self) -> str:
        """Generate a manifest of available skills for the agent system prompt.

        This creates a formatted list of skill names and descriptions
        that the agent can use to decide when to invoke a skill.
        """
        active = self._active_skills()
        if not active:
            return ""

        lines = ["<available_skills>"]
        for skill in active:
            name = skill["name"]
            desc = skill["description"]
            lines.append(f"- **{name}**: {desc}")
        lines.append("</available_skills>")
        return "\n".join(lines)

    def get_skill_resources_path(self, name: str, resource_type: str = "scripts") -> Path | None:
        """Get path to a skill's resource directory (scripts/, references/, assets/).

        Args:
            name: Skill name.
            resource_type: One of "scripts", "references", "assets".

        Returns:
            Path to the resource directory if it exists, else None.
        """
        skill = self._skills.get(name)
        if skill is None:
            return None
        skill_path = skill.get("path")
        if skill_path is None:
            return None
        resource_path = skill_path / resource_type
        return resource_path if resource_path.is_dir() else None

    def list_skills(self) -> list[dict[str, Any]]:
        """Return metadata for all registered skills."""
        return [
            {
                "name": s["name"],
                "description": s["description"],
                "source": s.get("source", "unknown"),
                "enabled": s["name"] not in self._disabled,
                "has_scripts": (s.get("path") / "scripts").is_dir() if s.get("path") else False,
            }
            for s in self._skills.values()
        ]

    def list_active_skill_names(self) -> list[str]:
        """Return names of all active (enabled) skills."""
        return [s["name"] for s in self._active_skills()]
