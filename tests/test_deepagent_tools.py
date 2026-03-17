from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from tests.conftest import build_test_agent_loop, build_test_vibe_config
from tests.mock.utils import mock_llm_chunk
from tests.stubs.fake_backend import FakeBackend
from vibe.core.agents.models import BuiltinAgentName
from vibe.core.deepagent import DeepAgentRuntime
from vibe.core.deepagent.adapters import build_langchain_tools
from vibe.core.tools.base import BaseToolConfig, ToolPermission
from vibe.core.trusted_folders import trusted_folders_manager
from vibe.core.types import (
    AssistantEvent,
    BaseEvent,
    FunctionCall,
    ToolCall,
    ToolCallEvent,
    ToolResultEvent,
    UserMessageEvent,
)


def _make_read_file_config() -> object:
    return build_test_vibe_config(
        enabled_tools=["read_file"],
        tools={"read_file": BaseToolConfig(permission=ToolPermission.ALWAYS)},
        system_prompt_id="tests",
        include_project_context=False,
        include_prompt_detail=False,
    )


def _write_skill(skills_root: Path, skill_name: str) -> None:
    skill_dir = skills_root / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        (
            "---\n"
            f"name: {skill_name}\n"
            f"description: Test skill for {skill_name}\n"
            "---\n\n"
            f"# {skill_name}\n"
        ),
        encoding="utf-8",
    )


def test_deepagent_runtime_builds_skill_mounts_from_vibe_discovery(
    tmp_working_directory: Path,
) -> None:
    trusted_folders_manager.add_trusted(tmp_working_directory)

    agents_skills_dir = tmp_working_directory / ".agents" / "skills"
    vibe_skills_dir = tmp_working_directory / ".vibe" / "skills"
    custom_skills_dir = tmp_working_directory / "custom-skills"

    _write_skill(agents_skills_dir, "agents-skill")
    _write_skill(vibe_skills_dir, "project-skill")
    _write_skill(custom_skills_dir, "custom-skill")

    config = build_test_vibe_config(skill_paths=[custom_skills_dir])
    agent_loop = build_test_agent_loop(config=config, backend=FakeBackend())
    runtime = DeepAgentRuntime(agent_loop)

    mounts = runtime._build_skill_mounts()
    mounts_by_kind = {mount.source_kind: mount for mount in mounts}

    assert mounts_by_kind["project-agents-skills"].path == agents_skills_dir.resolve()
    assert mounts_by_kind["project-agents-skills"].skill_names == ("agents-skill",)
    assert mounts_by_kind["project-vibe-skills"].path == vibe_skills_dir.resolve()
    assert mounts_by_kind["project-vibe-skills"].skill_names == ("project-skill",)
    assert mounts_by_kind["config-skill-path"].path == custom_skills_dir.resolve()
    assert mounts_by_kind["config-skill-path"].skill_names == ("custom-skill",)
    assert runtime._build_skill_sources(mounts) == [mount.source for mount in mounts]


def test_deepagent_runtime_mounts_active_agent_builtin_skill_scope() -> None:
    config = build_test_vibe_config(
        system_prompt_id="tests",
        include_project_context=False,
        include_prompt_detail=False,
    )
    agent_loop = build_test_agent_loop(
        config=config, agent_name=BuiltinAgentName.PLANNER, backend=FakeBackend()
    )
    runtime = DeepAgentRuntime(agent_loop)

    mounts = runtime._build_skill_mounts()

    assert any(
        mount.source_kind == "builtin-agent-skill-scope"
        and mount.path.name == "planner"
        and mount.skill_names == ("planner",)
        for mount in mounts
    )
    assert not any(
        mount.source_kind == "builtin-agent-skill-scope"
        and mount.path.name == "explore"
        for mount in mounts
    )


@pytest.mark.asyncio
async def test_build_langchain_tools_includes_git_snapshot_tools() -> None:
    agent_loop = build_test_agent_loop(
        config=build_test_vibe_config(
            system_prompt_id="tests",
            include_project_context=False,
            include_prompt_detail=False,
        ),
        backend=FakeBackend(),
    )

    emitted_events: list[BaseEvent] = []

    async def emit_event(event: BaseEvent) -> None:
        emitted_events.append(event)

    tools = build_langchain_tools(
        agent_loop,
        emit_event=emit_event,
        on_tool_started=lambda: None,
        on_tool_finished=lambda: None,
    )

    tool_names = {tool.name for tool in tools}
    assert "git" in tool_names
    assert "git_worktree" in tool_names
    assert "snapshot" in tool_names


@pytest.mark.asyncio
async def test_langchain_tool_runner_accepts_missing_tool_call_id(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello deepagent\n", encoding="utf-8")

    agent_loop = build_test_agent_loop(
        config=_make_read_file_config(),
        agent_name=BuiltinAgentName.AUTO_APPROVE,
        backend=FakeBackend(),
    )

    emitted_events: list[BaseEvent] = []

    async def emit_event(event: BaseEvent) -> None:
        emitted_events.append(event)

    tools = build_langchain_tools(
        agent_loop,
        emit_event=emit_event,
        on_tool_started=lambda: None,
        on_tool_finished=lambda: None,
    )
    read_file_tool = next(tool for tool in tools if tool.name == "read_file")

    result = await read_file_tool.ainvoke({"path": str(file_path)})

    assert "hello deepagent" in result
    tool_result_events = [
        event for event in emitted_events if isinstance(event, ToolResultEvent)
    ]
    assert len(tool_result_events) == 1
    assert tool_result_events[0].tool_name == "read_file"
    assert tool_result_events[0].error is None
    assert tool_result_events[0].tool_call_id


@pytest.mark.asyncio
@pytest.mark.skipif(
    not DeepAgentRuntime.is_supported(),
    reason="DeepAgent runtime dependencies are not installed",
)
async def test_deepagent_runtime_emits_tool_events_for_vibe_tools(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello from runtime\n", encoding="utf-8")

    tool_call = ToolCall(
        id="tc_read_file",
        index=0,
        function=FunctionCall(
            name="read_file", arguments=json.dumps({"path": str(file_path)})
        ),
    )
    backend = FakeBackend([
        [mock_llm_chunk(content="I will inspect the file.", tool_calls=[tool_call])],
        [mock_llm_chunk(content="The file says hello from runtime.")],
    ])
    agent_loop = build_test_agent_loop(
        config=_make_read_file_config(),
        agent_name=BuiltinAgentName.AUTO_APPROVE,
        backend=backend,
        use_deepagent=True,
    )

    events = [event async for event in agent_loop.act("check the file")]

    assert any(isinstance(event, UserMessageEvent) for event in events)
    assert any(
        isinstance(event, ToolCallEvent) and event.tool_name == "read_file"
        for event in events
    )

    tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
    assert any(
        event.tool_name == "read_file"
        and event.error is None
        and event.result is not None
        for event in tool_results
    )

    assistant_text = "".join(
        event.content for event in events if isinstance(event, AssistantEvent)
    )
    assert "The file says hello from runtime." in assistant_text


@pytest.mark.asyncio
@pytest.mark.skipif(
    not DeepAgentRuntime.is_supported(),
    reason="DeepAgent runtime dependencies are not installed",
)
async def test_deepagent_runtime_logs_explicit_contract(
    tmp_working_directory: Path, caplog: pytest.LogCaptureFixture
) -> None:
    trusted_folders_manager.add_trusted(tmp_working_directory)
    agents_skills_dir = tmp_working_directory / ".agents" / "skills"
    _write_skill(agents_skills_dir, "agents-skill")

    config = build_test_vibe_config(
        system_prompt_id="tests",
        include_project_context=False,
        include_prompt_detail=False,
    )
    agent_loop = build_test_agent_loop(
        config=config, agent_name=BuiltinAgentName.AUTO_APPROVE, backend=FakeBackend()
    )
    runtime = DeepAgentRuntime(agent_loop)

    with caplog.at_level(logging.INFO, logger="vibe"):
        await runtime._ensure_agent()

    contract = runtime.runtime_contract
    assert contract is not None
    assert contract.orchestrator == "langchain.create_agent"
    assert contract.tool_adapter == "build_langchain_tools"
    assert contract.backend == "FilesystemBackend"
    assert contract.checkpointer == "InMemorySaver"
    assert contract.thread_id_source == "AgentLoop.conversation_id"
    assert "PatchToolCallsMiddleware" in contract.middleware
    assert "SkillsMiddleware" in contract.middleware
    assert any(
        mount.source_kind == "project-agents-skills"
        and mount.path == agents_skills_dir.resolve()
        for mount in contract.skill_mounts
    )

    log_messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Configured DeepAgent runtime orchestrator=langchain.create_agent" in message
        for message in log_messages
    )
    assert any(
        "Mounted DeepAgent skill source kind=project-agents-skills" in message
        and str(agents_skills_dir.resolve()) in message
        for message in log_messages
    )
