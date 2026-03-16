from __future__ import annotations

from pathlib import Path
from typing import Any
import sys
import types

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from pydantic import ConfigDict, Field

from malibu.agent.tools import build_default_tools
from malibu.config import get_settings


class ToolCallingFakeModel(GenericFakeChatModel):
    """Fake chat model that supports LangChain tool binding."""

    bound_tools: list[Any] = Field(default_factory=list, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def bind_tools(self, tools, tool_choice=None, **kwargs):  # noqa: ANN001, ARG002
        object.__setattr__(self, "bound_tools", list(tools))
        return self


def test_native_tools_execute_inside_langchain_agent(tmp_path: Path):
    target = tmp_path / "note.txt"
    target.write_text("Malibu tool invocation works.", encoding="utf-8")

    tools = build_default_tools(
        settings=get_settings(),
        cwd=tmp_path,
        session_id="langchain-agent-test",
    )
    read_tool = next(tool for tool in tools if tool.name == "read_file")

    model = ToolCallingFakeModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "read_file",
                            "args": {"file_path": str(target)},
                            "id": "call-read-file",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Finished reading the file."),
            ]
        )
    )

    agent = create_agent(
        model=model,
        tools=[read_tool],
        system_prompt="Use the available tools to answer the user.",
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Read the note file."}]}
    )

    assert [tool.name for tool in model.bound_tools] == ["read_file"]
    assert result["messages"][-1].content == "Finished reading the file."
    assert "Malibu tool invocation works." in result["messages"][-2].content


def test_native_filesystem_tools_preserve_public_alias_args(tmp_path: Path):
    target = tmp_path / "note.txt"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    tools = {
        tool.name: tool
        for tool in build_default_tools(
            settings=get_settings(),
            cwd=tmp_path,
            session_id="langchain-filesystem-compat-test",
        )
    }

    read_content = tools["read_file"].invoke(
        {"file_path": str(target), "line": 2, "limit": 1}
    )
    assert "beta" in read_content
    assert "alpha" not in read_content

    grep_result = tools["grep"].invoke(
        {
            "pattern": "beta",
            "path": str(tmp_path),
            "glob_pattern": "*.txt",
            "max_results": 1,
        }
    )
    assert "beta" in grep_result
    assert "note.txt" in grep_result


def test_build_agent_passes_native_tool_bundle_to_deep_agents(
    monkeypatch,
    tmp_path: Path,
):
    acp_module = types.ModuleType("acp")
    acp_schema = types.ModuleType("acp.schema")

    class _FakeSessionMode:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _FakeSessionModeState:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    acp_schema.SessionMode = _FakeSessionMode
    acp_schema.SessionModeState = _FakeSessionModeState
    acp_module.schema = acp_schema
    monkeypatch.setitem(sys.modules, "acp", acp_module)
    monkeypatch.setitem(sys.modules, "acp.schema", acp_schema)

    import malibu.agent.graph as graph_module
    import malibu.agent.subagents.loader as subagent_loader

    captured: dict[str, Any] = {}

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return "fake-agent"

    monkeypatch.setattr(graph_module, "create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(graph_module, "load_local_context", lambda cwd: "")
    monkeypatch.setattr(
        graph_module,
        "build_system_prompt",
        lambda **kwargs: "system prompt",
    )
    monkeypatch.setattr(graph_module, "build_middleware_stack", lambda *args, **kwargs: [])
    monkeypatch.setattr(subagent_loader, "list_subagents", lambda **kwargs: [])

    settings = get_settings().model_copy(
        update={
            "llm_api_key": "",
            "llm_base_url": None,
            "llm_model": "openai:gpt-5.4",
        }
    )

    agent = graph_module.build_agent(
        settings=settings,
        cwd=str(tmp_path),
        extra_tools=[],
    )

    assert agent == "fake-agent"
    tool_names = {tool.name for tool in captured["tools"]}
    assert {
        "read_file",
        "write_file",
        "edit_file",
        "ls",
        "grep",
        "execute",
        "apply_patch",
        "ast_grep",
        "str_replace",
        "lsp",
        "write_todos",
    }.issubset(tool_names)
    assert captured["system_prompt"] == "system prompt"
