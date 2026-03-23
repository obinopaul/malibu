from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from malibu.agent.tool_server.tools.base import BaseTool, ToolResult
from malibu.config import get_settings


class _FakeTool(BaseTool):
    name = "fake_echo"
    display_name = "Fake Echo"
    description = "Echo the provided name."
    input_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name to echo.",
            }
        },
        "required": ["name"],
    }
    read_only = True

    async def execute(self, tool_input: dict[str, str]) -> ToolResult:
        return ToolResult(llm_content=f"hello {tool_input['name']}")


def test_tools_package_does_not_eagerly_import_server_only_modules():
    import malibu.agent.tools as tools

    assert callable(tools.build_default_tools)
    assert "deepagents.backends.local" not in sys.modules
    assert "mcp" not in sys.modules
    assert "fastmcp" not in sys.modules

    names = {tool.name for tool in tools.ALL_TOOLS}
    assert {"read_file", "write_file", "edit_file", "ls", "grep", "execute", "write_todos"}.issubset(names)
    assert "deepagents.backends.local" not in sys.modules
    assert "mcp" not in sys.modules
    assert "fastmcp" not in sys.modules


def test_default_bundle_uses_tool_server_filesystem_tools(tmp_path: Path):
    from malibu.agent.tools import build_default_tools
    from malibu.agent.tools.adapters import ProjectToolAdapter
    from malibu.agent.tool_server.tools.file_system.file_edit_tool import FileEditTool
    from malibu.agent.tool_server.tools.file_system.file_read_tool import FileReadTool
    from malibu.agent.tool_server.tools.file_system.file_write_tool import (
        FileWriteTool,
    )
    from malibu.agent.tool_server.tools.file_system.grep_tool import GrepTool

    tools = {
        tool.name: tool
        for tool in build_default_tools(
            settings=get_settings(),
            cwd=tmp_path,
            session_id="packaging-filesystem-test",
        )
    }

    assert isinstance(tools["read_file"], ProjectToolAdapter)
    assert isinstance(tools["read_file"].wrapped_tool, FileReadTool)
    assert isinstance(tools["write_file"].wrapped_tool, FileWriteTool)
    assert isinstance(tools["edit_file"].wrapped_tool, FileEditTool)
    assert isinstance(tools["grep"].wrapped_tool, GrepTool)


def test_agent_package_lazy_exports_do_not_require_graph_import():
    import malibu.agent as agent_pkg

    names = {tool.name for tool in agent_pkg.ALL_TOOLS}
    assert "read_file" in names
    assert "deepagents.backends.local" not in sys.modules


def test_legacy_tool_server_get_langchain_tools_uses_native_bundle():
    import malibu.agent.tool_server.tools as legacy_tools

    tools = legacy_tools.get_langchain_tools(str(Path.cwd()), {})
    names = {tool.name for tool in tools}

    assert {"read_file", "shell_run", "web_search", "write_todos"}.issubset(names)
    assert "mcp" not in sys.modules
    assert "fastmcp" not in sys.modules


def test_legacy_langchain_adapter_wraps_project_tools_without_mcp():
    from malibu.agent.tool_server.tools.langchain_adapter import (
        LangChainToolAdapter,
        adapt_tools_for_langchain,
        json_schema_to_pydantic_model,
    )

    schema = json_schema_to_pydantic_model("FakeEcho", _FakeTool.input_schema)
    assert "name" in schema.model_fields

    tool = LangChainToolAdapter.from_base_tool(_FakeTool())
    assert tool.invoke({"name": "malibu"}) == "hello malibu"

    adapted = adapt_tools_for_langchain([_FakeTool()])
    assert len(adapted) == 1
    assert adapted[0].name == "fake_echo"


def test_legacy_langchain_tool_registry_filters_native_bundle():
    from malibu.agent.tool_server.tools.langchain_tools import get_all_langchain_tools

    tools = get_all_langchain_tools(
        str(Path.cwd()),
        {},
        include_browser=False,
        include_shell=False,
        include_media=False,
        include_dev=False,
        include_agent=False,
    )
    names = {tool.name for tool in tools}

    assert "read_file" in names
    assert "web_search" in names
    assert "browser_click" not in names
    assert "shell_run" not in names


def test_shell_package_exports_local_manager_only():
    from malibu.agent.tool_server.tools import shell as shell_pkg

    assert hasattr(shell_pkg, "LocalShellSessionManager")
    assert hasattr(shell_pkg, "BaseShellManager")
    assert not hasattr(shell_pkg, "TmuxSessionManager")
    assert not hasattr(shell_pkg, "TmuxWindowManager")


def test_dev_package_no_longer_exports_server_only_tools():
    from malibu.agent.tool_server.tools import dev as dev_pkg

    assert hasattr(dev_pkg, "FullStackInitTool")
    assert hasattr(dev_pkg, "SaveCheckpointTool")
    assert not hasattr(dev_pkg, "RegisterPort")
    assert not hasattr(dev_pkg, "GetDatabaseConnection")


def test_browser_package_import_does_not_pull_mcp_clients():
    import malibu.agent.tool_server.browser as browser_pkg

    assert hasattr(browser_pkg, "Browser")
    assert "mcp" not in sys.modules
    assert "fastmcp" not in sys.modules


def test_base_tool_mcp_wrapper_is_disabled():
    with pytest.raises(RuntimeError, match="MCP transport wrappers were removed"):
        asyncio.run(_FakeTool()._mcp_wrapper({"name": "malibu"}))
