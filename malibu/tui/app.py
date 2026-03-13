"""MalibuApp — main Textual application for the Malibu terminal coordinator.

Manages the ACP connection lifecycle, slash-command dispatch, and screen
navigation.  The heavy lifting is done by the :class:`TUIBridge` which routes
ACP callbacks into Textual message posting.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from textual import work
from textual.app import App
from textual.binding import Binding

from malibu.tui.bridge import SessionUpdateMessage, PermissionRequestMessage, TUIBridge
from malibu.tui.commands import SlashCommandRegistry, create_default_registry, CommandContext
from malibu.tui.screens.chat import ChatScreen
from malibu.tui.screens.welcome import WelcomeScreen


class MalibuApp(App):
    """Textual application wrapping the ACP agent client."""

    TITLE = "Malibu"
    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding("ctrl+c", "cancel", "Cancel", show=False),
        Binding("ctrl+d", "quit", "Quit", show=False),
    ]

    def __init__(
        self,
        *,
        cwd: str = ".",
        initial_prompt: str | None = None,
        continue_session: bool = False,
        resume_session_id: str | None = None,
        no_welcome: bool = False,
    ) -> None:
        super().__init__()
        self._cwd = str(Path(cwd).resolve())
        self._conn: Any | None = None
        self._session_id: str | None = None
        self._bridge: TUIBridge | None = None
        self._command_registry: SlashCommandRegistry = create_default_registry()
        self._process: Any | None = None
        self._closing: bool = False
        self._initial_prompt: str | None = initial_prompt
        self._continue_session: bool = continue_session
        self._resume_session_id: str | None = resume_session_id
        self._no_welcome: bool = no_welcome

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """Show welcome screen (if enabled) then start the ACP connection."""
        from malibu.config import get_settings

        settings = get_settings()
        if settings.tui_show_welcome and not self._no_welcome:
            self.push_screen(WelcomeScreen())
        else:
            self.push_screen(ChatScreen())

        self._start_agent()

    @work(exclusive=True, group="agent")
    async def _start_agent(self) -> None:
        """Spawn the agent subprocess and connect via ACP."""
        await self._connect_agent()

    async def _connect_agent(self) -> None:
        """Establish ACP connection to the agent subprocess."""
        from acp import PROTOCOL_VERSION

        from malibu.client.client import MalibuClient
        from malibu.config import get_settings
        from malibu.local_agent_connection import connect_local_agent
        from malibu.mcp.discovery import discover_mcp_servers
        from malibu.telemetry.logging import setup_logging

        settings = get_settings()
        setup_logging(settings)

        self._bridge = TUIBridge(self)
        client = MalibuClient(
            settings,
            cwd=self._cwd,
            display_handler=self._bridge.display_handler,
            permission_handler=self._bridge.permission_handler,
        )

        # Discover MCP servers
        mcp_servers = discover_mcp_servers(self._cwd)

        async with connect_local_agent(client, settings=settings) as (conn, process):
            self._conn = conn
            self._process = process

            # Drain agent stderr
            stderr_task = asyncio.create_task(self._drain_stderr(process))

            try:
                await asyncio.wait_for(
                    conn.initialize(protocol_version=PROTOCOL_VERSION, client_capabilities=None),
                    timeout=15.0,
                )
                session = await asyncio.wait_for(
                    conn.new_session(mcp_servers=mcp_servers, cwd=self._cwd),
                    timeout=15.0,
                )
                self._session_id = session.session_id

                # Send initial prompt if provided (e.g. from bare CLI arg)
                if self._initial_prompt:
                    prompt = self._initial_prompt
                    self._initial_prompt = None  # Only send once
                    from acp import text_block
                    try:
                        await conn.prompt(
                            session_id=session.session_id,
                            prompt=[text_block(prompt)],
                        )
                    except Exception:
                        pass

                # Block until the app exits
                while not self._closing:
                    await asyncio.sleep(0.5)
            finally:
                stderr_task.cancel()

        await client.cleanup()

    async def _drain_stderr(self, process: Any) -> None:
        """Read subprocess stderr silently (logged, not displayed)."""
        if process.stderr is None:
            return
        try:
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Message dispatch (forwarded from bridge → active screen)
    # ------------------------------------------------------------------

    def on_session_update_message(self, message: SessionUpdateMessage) -> None:
        """Forward ACP session updates to the active screen."""
        screen = self.screen
        if hasattr(screen, "handle_session_update"):
            screen.handle_session_update(message)

    def on_permission_request_message(self, message: PermissionRequestMessage) -> None:
        """Forward permission requests to the active screen."""
        screen = self.screen
        if hasattr(screen, "handle_permission_request"):
            screen.handle_permission_request(message)

    # ------------------------------------------------------------------
    # Public API — used by ChatScreen and commands
    # ------------------------------------------------------------------

    @work(group="prompt")
    async def send_prompt(self, text: str) -> None:
        """Send a user prompt to the agent — called from ChatScreen."""
        await self._send_prompt_async(text)

    async def _send_prompt_async(self, text: str) -> None:
        """Dispatch text as slash-command or ACP prompt."""
        if self._conn is None or self._session_id is None:
            return

        # Slash command?
        if self._command_registry.is_command(text):
            cmd_name, args = self._command_registry.parse(text)
            command = self._command_registry.get(cmd_name)
            if command:
                ctx = CommandContext(
                    app=self,
                    conn=self._conn,
                    session_id=self._session_id,
                )
                try:
                    await command.execute(ctx, args)
                except Exception as exc:
                    from malibu.tui.bridge import SessionUpdateMessage
                    from acp.schema import AgentMessageChunk, TextContentBlock

                    error_update = AgentMessageChunk(
                        session_update="agent_message_chunk",
                        content=TextContentBlock(type="text", text=f"Command error: {exc}"),
                    )
                    self.post_message(SessionUpdateMessage(self._session_id, error_update))
                return
            # Unknown command — fall through to agent

        from acp import text_block

        try:
            await self._conn.prompt(
                session_id=self._session_id,
                prompt=[text_block(text)],
            )
        except Exception as exc:
            from acp.schema import AgentMessageChunk, TextContentBlock

            error_update = AgentMessageChunk(
                session_update="agent_message_chunk",
                content=TextContentBlock(type="text", text=f"Error: {exc}"),
            )
            self.post_message(SessionUpdateMessage(self._session_id, error_update))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_cancel(self) -> None:
        """Cancel the current agent operation."""
        if self._conn and self._session_id:

            async def _cancel() -> None:
                try:
                    await self._conn.cancel(session_id=self._session_id)
                except Exception:
                    pass

            asyncio.ensure_future(_cancel())

    @property
    def conn(self) -> Any:
        return self._conn

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def command_registry(self) -> SlashCommandRegistry:
        return self._command_registry

    @property
    def cwd(self) -> str:
        return self._cwd

    def exit(self, result: object = None, *args: object, **kwargs: object) -> None:
        """Signal the agent loop to stop, then exit normally."""
        self._closing = True
        super().exit(result, *args, **kwargs)  # type: ignore[arg-type]
