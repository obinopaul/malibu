"""Main Textual application for the Malibu terminal shell."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
import time
from typing import Any

from textual import work
from textual.app import App
from textual.binding import Binding

from malibu.tui.bridge import (
    ExtensionNotificationMessage,
    ExtensionRequestMessage,
    PermissionRequestMessage,
    SessionUpdateMessage,
    TUIBridge,
)
from malibu.tui.commands import CommandContext, SlashCommandRegistry, create_default_registry
from malibu.tui.protocol import TUI_BOOTSTRAP_METHOD
from malibu.tui.screens.chat import ChatScreen
from malibu.tui.screens.welcome import WelcomeScreen
from malibu.tui.theme import MALIBU_CLOUD_THEME


class MalibuApp(App):
    """Composition root for the Malibu TUI."""

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
        self._initial_prompt = initial_prompt
        self._continue_session = continue_session
        self._resume_session_id = resume_session_id
        self._no_welcome = no_welcome

        self._conn: Any | None = None
        self._session_id: str | None = None
        self._process: Any | None = None
        self._bridge: TUIBridge | None = None
        self._closing = False
        self._mcp_servers: list[dict[str, Any]] = []
        self._quit_armed_at: float | None = None

        self._command_registry: SlashCommandRegistry = create_default_registry()
        self._chat_screen = ChatScreen()
        self.register_theme(MALIBU_CLOUD_THEME)
        self.theme = MALIBU_CLOUD_THEME.name

    def on_mount(self) -> None:
        self._chat_screen.set_shell_ready(False)
        self.install_screen(self._chat_screen, name="chat")
        if self._should_show_welcome():
            self.install_screen(WelcomeScreen(), name="welcome")
            self.push_screen("welcome")
        else:
            self.push_screen("chat")
        self._start_agent()

    def _should_show_welcome(self) -> bool:
        from malibu.config import get_settings

        settings = get_settings()
        return bool(settings.tui_show_welcome and not self._no_welcome)

    def show_chat_screen(self) -> None:
        """Switch from the welcome screen to the persistent chat shell."""
        self.switch_screen("chat")

    def _watch_theme(self, theme_name: str) -> None:
        super()._watch_theme(theme_name)
        self.call_next(self._chat_screen.refresh_theme)

    @work(exclusive=True, group="agent")
    async def _start_agent(self) -> None:
        await self._connect_agent()

    async def _connect_agent(self) -> None:
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
            extension_method_handler=self._bridge.extension_method_handler,
            extension_notification_handler=self._bridge.extension_notification_handler,
        )

        mcp_servers = discover_mcp_servers(self._cwd)
        self._mcp_servers = mcp_servers

        async with connect_local_agent(client, settings=settings) as (conn, process):
            self._conn = conn
            self._process = process
            stderr_task = asyncio.create_task(self._drain_stderr(process))

            try:
                await asyncio.wait_for(
                    conn.initialize(protocol_version=PROTOCOL_VERSION, client_capabilities=None),
                    timeout=15.0,
                )
                self._session_id = await self._open_session(conn, mcp_servers)
                await self._bootstrap_chat()

                if self._initial_prompt:
                    prompt = self._initial_prompt
                    self._initial_prompt = None
                    await self.dispatch_prompt(prompt)

                while not self._closing:
                    await asyncio.sleep(0.25)
            finally:
                stderr_task.cancel()

        await client.cleanup()

    async def _open_session(self, conn: Any, mcp_servers: list[dict[str, Any]]) -> str:
        if self._resume_session_id:
            await asyncio.wait_for(
                conn.resume_session(
                    session_id=self._resume_session_id,
                    cwd=self._cwd,
                    mcp_servers=mcp_servers,
                ),
                timeout=15.0,
            )
            return self._resume_session_id

        if self._continue_session:
            sessions = await asyncio.wait_for(conn.list_sessions(cwd=self._cwd), timeout=15.0)
            if sessions.sessions:
                session_id = sessions.sessions[0].session_id
                await asyncio.wait_for(
                    conn.resume_session(
                        session_id=session_id,
                        cwd=self._cwd,
                        mcp_servers=mcp_servers,
                    ),
                    timeout=15.0,
                )
                return session_id

        session = await asyncio.wait_for(
            conn.new_session(mcp_servers=mcp_servers, cwd=self._cwd),
            timeout=15.0,
        )
        return session.session_id

    async def _bootstrap_chat(self) -> None:
        if self._conn is None or self._session_id is None:
            return
        try:
            payload = await self._conn.ext_method(
                TUI_BOOTSTRAP_METHOD,
                {"session_id": self._session_id, "cwd": self._cwd},
            )
        except Exception:
            payload = {}
        self._chat_screen.load_bootstrap(payload)
        self.run_worker(self._chat_screen.message_controller.flush_ready_queue(), exclusive=False)

    async def new_session(self) -> None:
        if self._conn is None:
            return
        session = await self._conn.new_session(cwd=self._cwd, mcp_servers=self._mcp_servers)
        self._session_id = session.session_id
        self._chat_screen.action_clear_messages()
        await self._bootstrap_chat()

    async def resume_session(self, session_id: str) -> None:
        if self._conn is None:
            return
        await self._conn.resume_session(
            session_id=session_id,
            cwd=self._cwd,
            mcp_servers=self._mcp_servers,
        )
        self._session_id = session_id
        self._chat_screen.action_clear_messages()
        await self._bootstrap_chat()

    async def _drain_stderr(self, process: Any) -> None:
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
    # Bridge dispatch
    # ------------------------------------------------------------------

    def on_session_update_message(self, message: SessionUpdateMessage) -> None:
        self._chat_screen.handle_session_update(message)

    def on_permission_request_message(self, message: PermissionRequestMessage) -> None:
        self._chat_screen.handle_permission_request(message)

    def on_extension_request_message(self, message: ExtensionRequestMessage) -> None:
        self._chat_screen.handle_extension_request(message)

    def on_extension_notification_message(self, message: ExtensionNotificationMessage) -> None:
        self._chat_screen.handle_extension_notification(message)

    # ------------------------------------------------------------------
    # Prompt dispatch
    # ------------------------------------------------------------------

    @work(group="prompt")
    async def send_prompt(self, text: str) -> None:
        await self.dispatch_prompt(text)

    async def dispatch_prompt(self, text: str) -> None:
        if self._conn is None or self._session_id is None:
            return

        if self._command_registry.is_command(text):
            cmd_name, args = self._command_registry.parse(text)
            command = self._command_registry.get(cmd_name)
            if command is not None:
                ctx = CommandContext(app=self, conn=self._conn, session_id=self._session_id)
                await command.execute(ctx, args)
                return

        from acp import text_block
        from acp.schema import AgentMessageChunk, TextContentBlock

        try:
            await self._conn.prompt(session_id=self._session_id, prompt=[text_block(text)])
        except Exception as exc:
            update = AgentMessageChunk(
                session_update="agent_message_chunk",
                content=TextContentBlock(type="text", text=f"Error: {exc}"),
            )
            self.post_message(SessionUpdateMessage(self._session_id, update))

    # ------------------------------------------------------------------
    # Actions and properties
    # ------------------------------------------------------------------

    def action_cancel(self) -> None:
        now = time.monotonic()
        if self._quit_armed_at is not None and now - self._quit_armed_at < 1.5:
            self.action_quit()
            return

        self._quit_armed_at = now
        if self._conn and self._session_id:

            async def _cancel() -> None:
                try:
                    await self._conn.cancel(session_id=self._session_id)
                except Exception:
                    pass

            asyncio.ensure_future(_cancel())
        self.notify("Press Ctrl+C again to quit", severity="warning", timeout=1.5)

    def action_quit(self) -> None:
        self._quit_armed_at = None
        if self._closing:
            return
        self._closing = True
        with contextlib.suppress(Exception):
            self.workers.cancel_all()
        if self._process is not None:
            with contextlib.suppress(Exception):
                self._process.terminate()
            with contextlib.suppress(Exception):
                self._process.kill()
        self._process = None
        self._conn = None
        self._bridge = None
        self.exit()

    @property
    def conn(self) -> Any:
        return self._conn

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str | None) -> None:
        self._session_id = value

    @property
    def command_registry(self) -> SlashCommandRegistry:
        return self._command_registry

    @property
    def cwd(self) -> str:
        return self._cwd

    def exit(self, result: object = None, *args: object, **kwargs: object) -> None:
        self._closing = True
        super().exit(result, *args, **kwargs)  # type: ignore[arg-type]
