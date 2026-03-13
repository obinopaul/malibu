from __future__ import annotations

import time
from pathlib import Path

from malibu.agent.tools import build_default_tools
from malibu.config import get_settings


def _shell_tool_map(cwd: Path) -> dict[str, object]:
    tools = build_default_tools(settings=get_settings(), cwd=cwd, session_id="shell-test")
    return {tool.name: tool for tool in tools}


def test_shell_session_lifecycle(tmp_path: Path):
    tools = _shell_tool_map(tmp_path)

    init_result = tools["shell_init"].invoke({"session_name": "demo"})
    assert "initialized successfully" in init_result

    list_result = tools["shell_list"].invoke({})
    assert "demo" in list_result

    run_result = tools["shell_run"].invoke(
        {
            "session_name": "demo",
            "command": "echo shell_hello",
            "description": "Echo hello text",
        }
    )
    assert "shell_hello" in run_result

    view_result = tools["shell_view"].invoke({"session_names": ["demo"]})
    assert "shell_hello" in view_result

    stop_result = tools["shell_stop"].invoke({"session_name": "demo", "kill_session": True})
    assert "killed successfully" in stop_result


def test_shell_write_to_interactive_process(tmp_path: Path):
    tools = _shell_tool_map(tmp_path)
    tools["shell_init"].invoke({"session_name": "interactive"})

    tools["shell_run"].invoke(
        {
            "session_name": "interactive",
            "command": 'python -c "import sys; print(sys.stdin.readline().strip())"',
            "description": "Wait for one line of input",
            "wait_for_output": False,
        }
    )
    time.sleep(1.5)

    tools["shell_write"].invoke(
        {
            "session_name": "interactive",
            "input": "typed_value",
            "press_enter": True,
        }
    )
    time.sleep(1.5)

    view_result = tools["shell_view"].invoke({"session_names": ["interactive"]})
    assert "typed_value" in view_result

    tools["shell_stop"].invoke({"session_name": "interactive", "kill_session": True})
