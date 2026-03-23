from __future__ import annotations

import sys

import pytest

from tests.conftest import build_test_vibe_config
from vibe.core.agents import AgentManager
from vibe.core.agents.models import BuiltinAgentName
from vibe.core.skills.manager import SkillManager
from vibe.core.system_prompt import get_universal_system_prompt
from vibe.core.tools.manager import ToolManager


def test_get_universal_system_prompt_includes_windows_prompt_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("COMSPEC", "C:\\Windows\\System32\\cmd.exe")

    config = build_test_vibe_config(
        system_prompt_id="tests",
        include_project_context=False,
        include_prompt_detail=True,
        include_model_info=False,
        include_commit_signature=False,
    )
    tool_manager = ToolManager(lambda: config)
    skill_manager = SkillManager(lambda: config)
    agent_manager = AgentManager(lambda: config)

    prompt = get_universal_system_prompt(
        tool_manager, config, skill_manager, agent_manager
    )

    assert "You are Malibu, a super useful programming assistant." in prompt
    assert (
        "The operating system is Windows with shell `C:\\Windows\\System32\\cmd.exe`"
        in prompt
    )
    assert "DO NOT use Unix commands like `ls`, `grep`, `cat`" in prompt
    assert "Use: `dir` (Windows) for directory listings" in prompt
    assert "Use: backslashes (\\\\) for paths" in prompt
    assert "Check command availability with: `where command` (Windows)" in prompt
    assert "Script shebang: Not applicable on Windows" in prompt


def test_plan_agent_uses_planner_prompt() -> None:
    config = build_test_vibe_config(
        include_project_context=False,
        include_prompt_detail=False,
        include_model_info=False,
        include_commit_signature=False,
    )
    agent_manager = AgentManager(lambda: config, initial_agent=BuiltinAgentName.PLAN)
    tool_manager = ToolManager(lambda: agent_manager.config)
    skill_manager = SkillManager(
        lambda: agent_manager.config,
        active_agent_getter=lambda: agent_manager.active_profile,
    )

    prompt = get_universal_system_prompt(
        tool_manager, agent_manager.config, skill_manager, agent_manager
    )

    assert "You are Malibu's dedicated planner." in prompt


def test_explore_prompt_and_scoped_skills_are_reflected_in_system_prompt() -> None:
    config = build_test_vibe_config(
        include_project_context=False,
        include_prompt_detail=True,
        include_model_info=False,
        include_commit_signature=False,
    )
    agent_manager = AgentManager(lambda: config, initial_agent=BuiltinAgentName.EXPLORE)
    tool_manager = ToolManager(lambda: agent_manager.config)
    skill_manager = SkillManager(
        lambda: agent_manager.config,
        active_agent_getter=lambda: agent_manager.active_profile,
    )

    prompt = get_universal_system_prompt(
        tool_manager, agent_manager.config, skill_manager, agent_manager
    )

    assert "You are Malibu's code-explorer subagent." in prompt
    assert "code-explorer" in prompt
    assert "<name>planner</name>" not in prompt
    assert "**explore**" in prompt
    assert "**planner**" in prompt
