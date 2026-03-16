from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from malibu.config import Settings, get_settings

from .adapters import ProjectToolAdapter
from .compat import (
    build_execute_tool,
    build_git_tools,
    build_ls_tool,
    build_write_todos_tool,
)
from .runtime import ToolRuntime


def _build_file_system_tools(runtime: ToolRuntime) -> dict[str, Any]:
    from malibu.agent.tool_server.tools.file_system.ast_grep_tool import ASTGrepTool
    from malibu.agent.tool_server.tools.file_system.file_edit_tool import FileEditTool
    from malibu.agent.tool_server.tools.file_system.file_patch import ApplyPatchTool
    from malibu.agent.tool_server.tools.file_system.file_read_tool import FileReadTool
    from malibu.agent.tool_server.tools.file_system.file_write_tool import FileWriteTool
    from malibu.agent.tool_server.tools.file_system.grep_tool import GrepTool
    from malibu.agent.tool_server.tools.file_system.lsp_tool import LspTool
    from malibu.agent.tool_server.tools.file_system.str_replace_editor import (
        StrReplaceEditorTool,
    )

    workspace_manager = runtime.workspace_manager

    tools = [
        ProjectToolAdapter.from_project_tool(
            FileReadTool(workspace_manager),
            name="read_file",
            include_artifact=True,
        ),
        ProjectToolAdapter.from_project_tool(
            FileWriteTool(workspace_manager),
            name="write_file",
        ),
        ProjectToolAdapter.from_project_tool(
            FileEditTool(workspace_manager),
            name="edit_file",
            include_artifact=True,
        ),
        ProjectToolAdapter.from_project_tool(
            GrepTool(workspace_manager),
            name="grep",
        ),
        ProjectToolAdapter.from_project_tool(
            ApplyPatchTool(runtime.workspace_manager),
            name="apply_patch",
            include_artifact=True,
        ),
        ProjectToolAdapter.from_project_tool(
            ASTGrepTool(runtime.workspace_manager),
            name="ast_grep",
        ),
        ProjectToolAdapter.from_project_tool(
            StrReplaceEditorTool(runtime.workspace_manager),
            name="str_replace",
            include_artifact=True,
        ),
        ProjectToolAdapter.from_project_tool(
            LspTool(runtime.workspace_manager),
            name="lsp",
            include_artifact=True,
        ),
    ]
    return {tool.name: tool for tool in tools}


def _build_shell_tools(runtime: ToolRuntime) -> list[Any]:
    from malibu.agent.tool_server.tools.shell.shell_init import ShellInit
    from malibu.agent.tool_server.tools.shell.shell_list import ShellList
    from malibu.agent.tool_server.tools.shell.shell_run_command import ShellRunCommand
    from malibu.agent.tool_server.tools.shell.shell_stop_command import (
        ShellStopCommand,
    )
    from malibu.agent.tool_server.tools.shell.shell_view import ShellView
    from malibu.agent.tool_server.tools.shell.shell_write_to_process import (
        ShellWriteToProcessTool,
    )

    shell_manager = runtime.shell_manager
    workspace_manager = runtime.workspace_manager
    return [
        ProjectToolAdapter.from_project_tool(
            ShellInit(shell_manager, workspace_manager),
            name="shell_init",
        ),
        ProjectToolAdapter.from_project_tool(
            ShellRunCommand(shell_manager, workspace_manager),
            name="shell_run",
            include_artifact=True,
        ),
        ProjectToolAdapter.from_project_tool(
            ShellView(shell_manager),
            name="shell_view",
            include_artifact=True,
        ),
        ProjectToolAdapter.from_project_tool(
            ShellList(shell_manager),
            name="shell_list",
        ),
        ProjectToolAdapter.from_project_tool(
            ShellWriteToProcessTool(shell_manager),
            name="shell_write",
            include_artifact=True,
        ),
        ProjectToolAdapter.from_project_tool(
            ShellStopCommand(shell_manager),
            name="shell_stop",
            include_artifact=True,
        ),
    ]


def _build_browser_tools(runtime: ToolRuntime) -> list[Any]:
    from malibu.agent.tool_server.tools.browser.click import BrowserClickTool
    from malibu.agent.tool_server.tools.browser.drag import BrowserDragTool
    from malibu.agent.tool_server.tools.browser.dropdown import (
        BrowserGetSelectOptionsTool,
        BrowserSelectDropdownOptionTool,
    )
    from malibu.agent.tool_server.tools.browser.enter_text import BrowserEnterTextTool
    from malibu.agent.tool_server.tools.browser.enter_text_multiple_fields import (
        BrowserEnterMultipleTextsTool,
    )
    from malibu.agent.tool_server.tools.browser.navigate import (
        BrowserNavigationTool,
        BrowserRestartTool,
    )
    from malibu.agent.tool_server.tools.browser.press_key import BrowserPressKeyTool
    from malibu.agent.tool_server.tools.browser.scroll import (
        BrowserScrollDownTool,
        BrowserScrollUpTool,
    )
    from malibu.agent.tool_server.tools.browser.tab import (
        BrowserOpenNewTabTool,
        BrowserSwitchTabTool,
    )
    from malibu.agent.tool_server.tools.browser.view import BrowserViewTool
    from malibu.agent.tool_server.tools.browser.wait import BrowserWaitTool

    browser = runtime.browser
    tool_instances = [
        BrowserClickTool(browser),
        BrowserWaitTool(browser),
        BrowserViewTool(browser),
        BrowserScrollDownTool(browser),
        BrowserScrollUpTool(browser),
        BrowserSwitchTabTool(browser),
        BrowserOpenNewTabTool(browser),
        BrowserGetSelectOptionsTool(browser),
        BrowserSelectDropdownOptionTool(browser),
        BrowserNavigationTool(browser),
        BrowserRestartTool(browser),
        BrowserEnterTextTool(browser),
        BrowserPressKeyTool(browser),
        BrowserDragTool(browser),
        BrowserEnterMultipleTextsTool(browser),
    ]
    return [
        ProjectToolAdapter.from_project_tool(tool, include_artifact=True)
        for tool in tool_instances
    ]


def _build_web_media_tools(runtime: ToolRuntime) -> list[Any]:
    from malibu.agent.tool_server.tools.media.image_generate import ImageGenerateTool
    from malibu.agent.tool_server.tools.media.video_generate import VideoGenerateTool
    from malibu.agent.tool_server.tools.web.image_search_tool import ImageSearchTool
    from malibu.agent.tool_server.tools.web.read_remote_image import ReadRemoteImageTool
    from malibu.agent.tool_server.tools.web.web_batch_search_tool import (
        WebBatchSearchTool,
    )
    from malibu.agent.tool_server.tools.web.web_search_tool import WebSearchTool
    from malibu.agent.tool_server.tools.web.web_visit_compress import (
        WebVisitCompressTool,
    )
    from malibu.agent.tool_server.tools.web.web_visit_tool import WebVisitTool

    return [
        ProjectToolAdapter.from_project_tool(
            WebSearchTool(
                runtime.web_search_client,
                max_results=runtime.settings.web_search_max_results,
            ),
        ),
        ProjectToolAdapter.from_project_tool(
            WebBatchSearchTool(
                runtime.web_search_client,
                max_results=runtime.settings.web_search_max_results,
            ),
        ),
        ProjectToolAdapter.from_project_tool(
            WebVisitTool(runtime.web_visit_service),
        ),
        ProjectToolAdapter.from_project_tool(
            WebVisitCompressTool(runtime.web_visit_service),
        ),
        ProjectToolAdapter.from_project_tool(
            ImageSearchTool(
                runtime.image_search_client,
                max_results=runtime.settings.image_search_max_results,
            ),
        ),
        ProjectToolAdapter.from_project_tool(
            ReadRemoteImageTool(),
            include_artifact=True,
        ),
        ProjectToolAdapter.from_project_tool(
            ImageGenerateTool(
                runtime.workspace_manager,
                runtime.image_generation_client,
            ),
            include_artifact=True,
        ),
        ProjectToolAdapter.from_project_tool(
            VideoGenerateTool(
                runtime.workspace_manager,
                runtime.video_generation_client,
            ),
            include_artifact=True,
        ),
    ]


def _build_core_coding_tools(runtime: ToolRuntime) -> list[Any]:
    file_tools = _build_file_system_tools(runtime)
    return [
        build_write_todos_tool(runtime),
        file_tools["read_file"],
        file_tools["write_file"],
        file_tools["edit_file"],
        build_ls_tool(runtime),
        file_tools["grep"],
        build_execute_tool(runtime),
        file_tools["apply_patch"],
        file_tools["ast_grep"],
        file_tools["str_replace"],
        file_tools["lsp"],
    ]


def build_tools_for_runtime(runtime: ToolRuntime, *, tool_profile: str | None = None) -> list[Any]:
    profile = (tool_profile or runtime.settings.agent_tool_profile).lower()
    tools = _build_core_coding_tools(runtime)

    if profile == "full" or runtime.settings.agent_enable_shell_tools:
        tools.extend(_build_shell_tools(runtime))
    if profile == "full" or runtime.settings.agent_enable_browser_tools:
        tools.extend(_build_browser_tools(runtime))
    if profile == "full" or runtime.settings.agent_enable_web_media_tools:
        tools.extend(_build_web_media_tools(runtime))

    if (
        (profile == "full" or runtime.settings.agent_enable_git_tools)
        and runtime.settings.git_tools_enabled
        and shutil.which("git")
    ):
        tools.extend(build_git_tools(runtime))

    return tools


def build_default_tools(
    settings: Settings | None = None,
    cwd: str | Path | None = None,
    session_id: str | None = None,
    tool_profile: str | None = None,
) -> list[Any]:
    runtime = ToolRuntime(
        settings=settings or get_settings(),
        cwd=Path(cwd or Path.cwd()).resolve(),
        session_id=session_id or "default",
    )
    return build_tools_for_runtime(runtime, tool_profile=tool_profile)
