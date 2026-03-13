"""Skills middleware — bridges the skill registry with the agent graph.

Provides helper functions that the ``create_agent()`` call (or graph
builder) uses to inject skill metadata and instructions into prompts.
"""

from __future__ import annotations

from malibu.skills.registry import SkillRegistry


def get_skills_manifest(registry: SkillRegistry) -> str:
    """Return a formatted manifest of available skills for the system prompt.

    The manifest lists skill names and trigger descriptions, allowing
    the agent to decide when to load full skill instructions.
    """
    return registry.get_skills_manifest()


def get_skill_instructions(registry: SkillRegistry, skill_name: str) -> str | None:
    """Return the full markdown instructions for a specific skill.

    Called when the agent decides to invoke a skill based on the manifest.
    """
    return registry.get_skill_instructions(skill_name)


def build_skill_prompt_section(registry: SkillRegistry) -> str:
    """Build a prompt section with skill availability information.

    This generates content suitable for injection into the agent's
    system prompt, informing it about available skills and how to
    request skill instructions when needed.
    """
    manifest = registry.get_skills_manifest()
    if not manifest:
        return ""

    return f"""
## Skills System

You have access to domain-specific skills that provide specialized knowledge and workflows.
Review the available skills below. When a user request matches a skill's description,
you should mentally note that skill is available - its full instructions will be
injected into context automatically when triggered by matching requests.

{manifest}
""".strip()
