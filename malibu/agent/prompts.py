"""System prompts for the Malibu agent.

Supports both the simple ``build_system_prompt()`` API and the composable
``PromptComposer`` for modular prompt construction with skills and subagents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

_BASE_PROMPT = """\
You are Malibu, a production-grade AI coding assistant.

## Working Directory
{cwd}

## Current Mode
{mode}

## Capabilities
- Read, write, and edit files in the working directory.
- Execute shell commands with user approval.
- Search files with grep and glob.
- Create and manage execution plans (todos).
- Git operations: status, diff, log, commit, worktree management.
- Provide clear, concise explanations of your actions.

## Guidelines
1. Always read files before editing them — understand context first.
2. Make the minimal change necessary to complete the task.
3. When making multi-step changes, create a plan first using write_todos.
4. Run tests after making code changes when a test suite exists.
5. Explain your reasoning before taking actions.
6. If a task is ambiguous, ask for clarification rather than guessing.
7. Never expose secrets, credentials, or sensitive data in your output.
"""

_MODE_ADDENDA: dict[str, str] = {
    "plan": (
        "\n## Mode: Plan\n"
        "You are in Plan Mode. Focus on reasoning, analysis, and planning.\n"
        "Create detailed plans using write_todos before taking action.\n"
        "ALL tool calls require user approval — including read-only operations.\n"
        "Explain your reasoning thoroughly before each action.\n"
    ),
    "ask_before_edits": (
        "\n## Mode: Ask Before Edits\n"
        "All file edits, writes, shell commands, and plan changes require user approval.\n"
        "Explain what you intend to do and why before requesting each action.\n"
    ),
    "accept_edits": (
        "\n## Mode: Accept Edits\n"
        "File edits and writes are auto-approved. Shell commands and plan changes still\n"
        "require user approval. Use this efficiency wisely — double-check edits before\n"
        "applying them since the user trusts your judgment on file operations.\n"
    ),
    "accept_everything": (
        "\n## Mode: Accept Everything\n"
        "All operations are auto-approved. Proceed efficiently but carefully.\n"
        "The user places full trust in your judgment.\n"
    ),
}


def build_system_prompt(*, cwd: str, mode: str, extra_context: str | None = None) -> str:
    """Build the full system prompt for a session."""
    prompt = _BASE_PROMPT.format(cwd=cwd, mode=mode)
    addendum = _MODE_ADDENDA.get(mode, "")
    prompt += addendum
    if extra_context:
        prompt += f"\n## Additional Context\n{extra_context}\n"
    return prompt


# ═══════════════════════════════════════════════════════════════════
# Composable prompt system
# ═══════════════════════════════════════════════════════════════════


@dataclass
class PromptSection:
    """A composable section of the system prompt."""

    id: str
    content: str
    priority: int = 50  # lower = placed earlier
    condition: Callable[..., bool] | None = None


class PromptComposer:
    """Builds system prompts from composable sections.

    Sections are sorted by priority (ascending) and concatenated.
    Sections with a ``condition`` callable are only included when the
    condition returns True.
    """

    def __init__(self) -> None:
        self._sections: list[PromptSection] = []

    def add(self, section: PromptSection) -> None:
        self._sections.append(section)

    def remove(self, section_id: str) -> None:
        self._sections = [s for s in self._sections if s.id != section_id]

    def build(self, **context: Any) -> str:
        """Build the final prompt string from all active sections."""
        active = []
        for section in sorted(self._sections, key=lambda s: s.priority):
            if section.condition is not None and not section.condition(**context):
                continue
            active.append(section.content)
        return "\n\n".join(active)


def build_composer(*, cwd: str, mode: str, extra_context: str | None = None) -> PromptComposer:
    """Create a PromptComposer pre-loaded with the standard Malibu sections."""
    composer = PromptComposer()

    composer.add(PromptSection(
        id="identity",
        content="You are Malibu, a production-grade AI coding assistant.",
        priority=10,
    ))

    composer.add(PromptSection(
        id="working_dir",
        content=f"## Working Directory\n{cwd}",
        priority=20,
    ))

    composer.add(PromptSection(
        id="capabilities",
        content=(
            "## Capabilities\n"
            "- Read, write, and edit files in the working directory.\n"
            "- Execute shell commands with user approval.\n"
            "- Search files with grep and glob.\n"
            "- Create and manage execution plans (todos).\n"
            "- Delegate tasks to specialized subagents.\n"
            "- Provide clear, concise explanations of your actions."
        ),
        priority=30,
    ))

    composer.add(PromptSection(
        id="guidelines",
        content=(
            "## Guidelines\n"
            "1. Always read files before editing them — understand context first.\n"
            "2. Make the minimal change necessary to complete the task.\n"
            "3. When making multi-step changes, create a plan first using write_todos.\n"
            "4. Run tests after making code changes when a test suite exists.\n"
            "5. Explain your reasoning before taking actions.\n"
            "6. If a task is ambiguous, ask for clarification rather than guessing.\n"
            "7. Never expose secrets, credentials, or sensitive data in your output."
        ),
        priority=40,
    ))

    mode_text = _MODE_ADDENDA.get(mode, "")
    if mode_text:
        composer.add(PromptSection(
            id="mode_instructions",
            content=mode_text.strip(),
            priority=50,
        ))

    if extra_context:
        composer.add(PromptSection(
            id="local_context",
            content=f"## Additional Context\n{extra_context}",
            priority=90,
        ))

    return composer
