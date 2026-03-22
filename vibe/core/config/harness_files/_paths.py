from __future__ import annotations

from vibe.core.paths import MALIBU_HOME, GlobalPath

GLOBAL_TOOLS_DIR = GlobalPath(lambda: MALIBU_HOME.path / "tools")
GLOBAL_SKILLS_DIR = GlobalPath(lambda: MALIBU_HOME.path / "skills")
GLOBAL_AGENTS_DIR = GlobalPath(lambda: MALIBU_HOME.path / "agents")
GLOBAL_PROMPTS_DIR = GlobalPath(lambda: MALIBU_HOME.path / "prompts")
