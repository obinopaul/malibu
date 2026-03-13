"""Multi-level skill discovery and loading.

Discovery order (higher precedence overrides lower):
  0. builtin   — ``malibu/skills/builtin/`` (package built-ins)
  1. user-malibu — ``~/.malibu/skills/``
  2. user-agents — ``~/.agents/skills/`` (shared across agent tools)
  3. project-malibu — ``.malibu/skills/`` (relative to session cwd)
  4. project-agents — ``.agents/skills/`` (shared across agent tools)

Each skill is a directory containing a SKILL.md file with YAML frontmatter.
"""

from __future__ import annotations

from pathlib import Path

from malibu.skills.base import SkillMetadata, load_skill_from_path
from malibu.telemetry.logging import get_logger

log = get_logger(__name__)

_BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"
_USER_MALIBU_DIR = Path.home() / ".malibu" / "skills"
_USER_AGENTS_DIR = Path.home() / ".agents" / "skills"


class SkillLoader:
    """Discovers and loads skills from multiple directory levels."""

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = Path(cwd).resolve() if cwd else Path.cwd()
        self._project_malibu_dir = self._cwd / ".malibu" / "skills"
        self._project_agents_dir = self._cwd / ".agents" / "skills"

    # ── public API ────────────────────────────────────────────────

    def load_all(self) -> list[SkillMetadata]:
        """Discover and load skills from all levels.

        Returns a list of skill metadata dicts. If a skill ``name`` appears at
        multiple levels, the highest-precedence version wins.
        """
        seen: dict[str, SkillMetadata] = {}

        for level_name, directory, source in self._discovery_dirs():
            if not directory.is_dir():
                log.debug("skill_dir_missing", level=level_name, path=str(directory))
                continue
            for skill in self._load_from_directory(directory, source):
                seen[skill["name"]] = skill  # later levels override earlier

        loaded = list(seen.values())
        log.info("skills_loaded", count=len(loaded), names=[s["name"] for s in loaded])
        return loaded

    def get_skill(self, name: str) -> SkillMetadata | None:
        """Load a specific skill by name from the highest-precedence source."""
        for _level_name, directory, source in reversed(self._discovery_dirs()):
            if not directory.is_dir():
                continue
            skill_dir = directory / name
            if skill_dir.is_dir():
                skill = load_skill_from_path(skill_dir, source)
                if skill is not None:
                    return skill
        return None

    def list_skill_names(self) -> list[str]:
        """Return list of all available skill names (deduplicated)."""
        names: set[str] = set()
        for _level_name, directory, _source in self._discovery_dirs():
            if not directory.is_dir():
                continue
            for entry in directory.iterdir():
                if entry.is_dir() and (entry / "SKILL.md").is_file():
                    names.add(entry.name)
        return sorted(names)

    # ── internals ─────────────────────────────────────────────────

    def _discovery_dirs(self) -> list[tuple[str, Path, str]]:
        """Return (level_name, path, source) tuples in precedence order (lowest first)."""
        return [
            ("builtin", _BUILTIN_DIR, "built-in"),
            ("user-malibu", _USER_MALIBU_DIR, "user"),
            ("user-agents", _USER_AGENTS_DIR, "user"),
            ("project-malibu", self._project_malibu_dir, "project"),
            ("project-agents", self._project_agents_dir, "project"),
        ]

    def _load_from_directory(self, directory: Path, source: str) -> list[SkillMetadata]:
        """Load all skills from a single directory."""
        skills: list[SkillMetadata] = []
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            log.exception("skill_dir_read_error", path=str(directory))
            return skills

        for entry in entries:
            if not entry.is_dir():
                continue
            if entry.name.startswith("_") or entry.name.startswith("."):
                continue
            try:
                skill = load_skill_from_path(entry, source)
                if skill is not None:
                    skills.append(skill)
                    log.debug(
                        "skill_loaded",
                        name=skill["name"],
                        source=source,
                        path=str(entry),
                    )
            except Exception:
                log.exception("skill_load_error", path=str(entry), source=source)
        return skills
