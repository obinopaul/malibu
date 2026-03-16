"""MalibuClient — full ACP Client implementation with all 11 protocol methods.

Implements every method defined in ``acp.interfaces.Client``:

  1. request_permission    — interactive permission prompts
  2. session_update        — renders all 11 session update types
  3. write_text_file       — secure file writes
  4. read_text_file        — secure file reads
  5. create_terminal       — subprocess terminal creation
  6. terminal_output       — read terminal output
  7. release_terminal      — detach from terminal
  8. wait_for_terminal_exit — block until exit
  9. kill_terminal         — kill terminal process
 10. ext_method            — custom extension methods
 11. ext_notification      — custom extension notifications

Plus the on_connect callback.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from acp import Client
from acp.exceptions import RequestError
from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AvailableCommandsUpdate,
    ConfigOptionUpdate,
    CreateTerminalResponse,
    CurrentModeUpdate,
    EnvVariable,
    KillTerminalCommandResponse,
    PermissionOption,
    ReadTextFileResponse,
    ReleaseTerminalResponse,
    RequestPermissionResponse,
    SessionInfoUpdate,
    TerminalOutputResponse,
    ToolCallProgress,
    ToolCallStart,
    ToolCallUpdate,
    UsageUpdate,
    UserMessageChunk,
    WaitForTerminalExitResponse,
    WriteTextFileResponse,
)

from malibu.client.accumulator import MalibuSessionAccumulator
from malibu.client.file_ops import FileOperations
from malibu.client.permissions_ui import interactive_permission_prompt
from malibu.client.session_display import display_session_update
from malibu.client.terminal_mgr import TerminalManager
from malibu.config import Settings
from malibu.telemetry.logging import get_logger

if TYPE_CHECKING:
    from acp.interfaces import Agent

log = get_logger(__name__)


class MalibuClient(Client):
    """Production-grade ACP client with full protocol support.

    Accepts optional ``display_handler`` and ``permission_handler`` callbacks
    to support alternative UIs (e.g. the Textual TUI) while keeping the
    plain terminal mode as the default.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        cwd: str,
        display_handler: Any | None = None,
        permission_handler: Any | None = None,
        extension_method_handler: Any | None = None,
        extension_notification_handler: Any | None = None,
    ) -> None:
        self._settings = settings
        self._cwd = cwd
        self._file_ops = FileOperations(settings, cwd=cwd)
        self._terminal_mgr = TerminalManager(cwd=cwd)
        self._accumulator = MalibuSessionAccumulator()
        self._agent_conn: Agent | None = None
        self._display_handler = display_handler or display_session_update
        self._permission_handler = permission_handler or interactive_permission_prompt
        self._extension_method_handler = extension_method_handler
        self._extension_notification_handler = extension_notification_handler

    # ───────────────────────────────────────────────────────────
    # Connection lifecycle
    # ───────────────────────────────────────────────────────────

    def on_connect(self, conn: Agent) -> None:
        """Store the agent connection for sending requests."""
        self._agent_conn = conn
        log.info("connected_to_agent")

    # ───────────────────────────────────────────────────────────
    # 1. request_permission
    # ───────────────────────────────────────────────────────────

    async def request_permission(
        self,
        options: list[PermissionOption],
        session_id: str,
        tool_call: ToolCallUpdate,
        **kwargs: Any,
    ) -> RequestPermissionResponse:
        log.info("permission_requested", session_id=session_id, title=tool_call.title)
        return await self._permission_handler(options, tool_call)

    # ───────────────────────────────────────────────────────────
    # 2. session_update (all 11 update types)
    # ───────────────────────────────────────────────────────────

    async def session_update(
        self,
        session_id: str,
        update: UserMessageChunk
        | AgentMessageChunk
        | AgentThoughtChunk
        | ToolCallStart
        | ToolCallProgress
        | AgentPlanUpdate
        | AvailableCommandsUpdate
        | CurrentModeUpdate
        | ConfigOptionUpdate
        | SessionInfoUpdate
        | UsageUpdate,
        **kwargs: Any,
    ) -> None:
        # Feed into accumulator for state tracking
        self._accumulator.process_update(session_id, update)
        # Render to display (console or TUI)
        result = self._display_handler(session_id, update, **kwargs)
        if inspect.isawaitable(result):
            await result

    # ───────────────────────────────────────────────────────────
    # 3. write_text_file
    # ───────────────────────────────────────────────────────────

    async def write_text_file(
        self,
        content: str,
        path: str,
        session_id: str,
        **kwargs: Any,
    ) -> WriteTextFileResponse | None:
        return await self._file_ops.write_text_file(path, content)

    # ───────────────────────────────────────────────────────────
    # 4. read_text_file
    # ───────────────────────────────────────────────────────────

    async def read_text_file(
        self,
        path: str,
        session_id: str,
        limit: int | None = None,
        line: int | None = None,
        **kwargs: Any,
    ) -> ReadTextFileResponse:
        return await self._file_ops.read_text_file(path, line=line, limit=limit)

    # ───────────────────────────────────────────────────────────
    # 5. create_terminal
    # ───────────────────────────────────────────────────────────

    async def create_terminal(
        self,
        command: str,
        session_id: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: list[EnvVariable] | None = None,
        output_byte_limit: int | None = None,
        **kwargs: Any,
    ) -> CreateTerminalResponse:
        return await self._terminal_mgr.create_terminal(
            command, args=args, cwd=cwd, env=env, output_byte_limit=output_byte_limit,
        )

    # ───────────────────────────────────────────────────────────
    # 6. terminal_output
    # ───────────────────────────────────────────────────────────

    async def terminal_output(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> TerminalOutputResponse:
        return await self._terminal_mgr.terminal_output(terminal_id)

    # ───────────────────────────────────────────────────────────
    # 7. release_terminal
    # ───────────────────────────────────────────────────────────

    async def release_terminal(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> ReleaseTerminalResponse | None:
        return await self._terminal_mgr.release_terminal(terminal_id)

    # ───────────────────────────────────────────────────────────
    # 8. wait_for_terminal_exit
    # ───────────────────────────────────────────────────────────

    async def wait_for_terminal_exit(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> WaitForTerminalExitResponse:
        return await self._terminal_mgr.wait_for_terminal_exit(terminal_id)

    # ───────────────────────────────────────────────────────────
    # 9. kill_terminal
    # ───────────────────────────────────────────────────────────

    async def kill_terminal(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> KillTerminalCommandResponse | None:
        return await self._terminal_mgr.kill_terminal(terminal_id)

    # ───────────────────────────────────────────────────────────
    # 10. ext_method
    # ───────────────────────────────────────────────────────────

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._extension_method_handler is None:
            log.warning("ext_method_unhandled", method=method)
            raise RequestError.method_not_found(method)
        result = self._extension_method_handler(method, params)
        if inspect.isawaitable(result):
            return await result
        return result

    # ───────────────────────────────────────────────────────────
    # 11. ext_notification
    # ───────────────────────────────────────────────────────────

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        log.info("ext_notification", method=method)
        if self._extension_notification_handler is None:
            return
        result = self._extension_notification_handler(method, params)
        if inspect.isawaitable(result):
            await result

    # ───────────────────────────────────────────────────────────
    # Cleanup
    # ───────────────────────────────────────────────────────────

    async def cleanup(self) -> None:
        """Clean up resources (terminals, accumulators)."""
        await self._terminal_mgr.cleanup()
