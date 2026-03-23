"""Primary Cloud Code-style chat shell for Malibu."""

from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalGroup
from textual.screen import Screen

from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AvailableCommandsUpdate,
    ConfigOptionUpdate,
    CurrentModeUpdate,
    SessionInfoUpdate,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UsageUpdate,
    UserMessageChunk,
)

from malibu.agent.modes import DEFAULT_MODES
from malibu.tui.bridge import (
    ExtensionNotificationMessage,
    ExtensionRequestMessage,
    PermissionRequestMessage,
    SessionUpdateMessage,
)
from malibu.tui.controllers import (
    ApprovalPromptController,
    AskUserPromptController,
    AutocompletePopupController,
    MessageController,
    PlanApprovalController,
)
from malibu.tui.managers import DisplayLedger, InterruptManager, MessageHistory, RunPhase, RunState
from malibu.tui.protocol import TUI_INTERRUPT_METHOD
from malibu.tui.serialization import deserialize_session_update
from malibu.tui.screens.command_palette import CommandPaletteScreen
from malibu.tui.screens.session_browser import SessionBrowserScreen
from malibu.tui.services import ConsoleBufferManager, HistoryHydrator, SpinnerService, UpdateProcessor
from malibu.tui.widgets.activity_strip import ActivityStrip
from malibu.tui.widgets.autocomplete_popup import AutocompletePopup
from malibu.tui.widgets.chat_input import ChatTextArea, CompletionItem
from malibu.tui.widgets.conversation.log import ConversationLog
from malibu.tui.widgets.plan_panel import PlanPanel
from malibu.tui.widgets.status_bar import StatusBar
from malibu.tui.widgets.welcome_dock import WelcomeDock


class ChatScreen(Screen):
    """Main terminal shell screen."""

    BINDINGS = [
        Binding("ctrl+shift+p", "toggle_plan", "Plan", show=True),
        Binding("ctrl+l", "clear_messages", "Clear", show=True),
        Binding("ctrl+k", "open_command_palette", "Commands", show=True),
        Binding("ctrl+o", "open_session_picker", "Sessions", show=True),
        Binding("end", "jump_to_latest", "Latest", show=False),
    ]

    DEFAULT_CSS = """
    ChatScreen {
        layout: vertical;
        background: $background;
        color: $foreground;
    }
    #shell-body {
        height: 1fr;
        min-height: 0;
        layout: horizontal;
    }
    #conversation-column {
        width: 1fr;
        height: 1fr;
        min-height: 0;
    }
    #welcome-dock {
        width: 1fr;
    }
    #composer {
        height: 6;
        min-height: 6;
        max-height: 16;
        layout: vertical;
        padding: 0 1 1 1;
        background: $background;
    }
    #composer-status {
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.display_ledger = DisplayLedger()
        self.history = MessageHistory()
        self.interrupt_manager = InterruptManager()
        self.console_buffers = ConsoleBufferManager()
        self.spinner_service = SpinnerService()

        self.status_bar: StatusBar | None = None
        self.welcome_dock: WelcomeDock | None = None
        self.conversation: ConversationLog | None = None
        self.plan_panel: PlanPanel | None = None
        self.chat_input: ChatTextArea | None = None
        self.autocomplete_popup: AutocompletePopup | None = None
        self.composer: VerticalGroup | None = None
        self.composer_status: ActivityStrip | None = None

        self.update_processor = UpdateProcessor(self)
        self.history_hydrator = HistoryHydrator(self.update_processor)
        self.message_controller = MessageController(self)
        self.autocomplete_controller: AutocompletePopupController | None = None
        self.approval_controller = ApprovalPromptController(self, self.interrupt_manager)
        self.plan_controller = PlanApprovalController(self, self.interrupt_manager)
        self.ask_user_controller = AskUserPromptController(self, self.interrupt_manager)

        self._available_commands: list[str] = []
        self._config_values: dict[str, str] = {}
        self._session_candidates: list[dict[str, Any]] = []
        self._model_candidates: list[str] = []
        self._mode_candidates: list[dict[str, str]] = [
            {
                "id": mode.id,
                "name": mode.name,
                "description": mode.description or "",
            }
            for mode in DEFAULT_MODES.available_modes
        ]
        self._spinner_timer = None
        self._shell_ready = True
        self._activity_started = False
        self._input_locked = False
        self._input_lock_reason = ""
        self._run_state = RunState()
        self._prompt_watchdog: asyncio.Task[None] | None = None
        self._run_activity_seen = False
        self._pending_remote_user_echoes: deque[str] = deque()

    def compose(self) -> ComposeResult:
        self.status_bar = StatusBar(cwd=str(Path.cwd()))
        self.welcome_dock = WelcomeDock(cwd=str(Path.cwd()))
        self.conversation = ConversationLog()
        self.plan_panel = PlanPanel()
        self.autocomplete_popup = AutocompletePopup(max_visible_rows=6)
        self.chat_input = ChatTextArea(
            history=self.history,
            completion_provider=self._build_completions,
        )
        self.composer = VerticalGroup(id="composer")
        self.composer_status = ActivityStrip()
        yield self.status_bar
        yield self.welcome_dock
        with Horizontal(id="shell-body"):
            with Vertical(id="conversation-column"):
                yield self.conversation
            yield self.plan_panel
        with self.composer:
            yield self.chat_input
            yield self.autocomplete_popup
            yield self.composer_status

    def on_mount(self) -> None:
        self.autocomplete_controller = AutocompletePopupController(self.query_one(AutocompletePopup))
        self.status_bar = self.query_one(StatusBar)
        self.welcome_dock = self.query_one(WelcomeDock)
        self.conversation = self.query_one(ConversationLog)
        self.plan_panel = self.query_one(PlanPanel)
        self.chat_input = self.query_one(ChatTextArea)
        self.composer_status = self.query_one(ActivityStrip)
        self._spinner_timer = self.set_interval(0.12, self._tick_spinner)
        self.chat_input.focus()
        self.status_bar.set_cwd(self.app.cwd)  # type: ignore[attr-defined]
        if self.welcome_dock is not None:
            self.welcome_dock.set_cwd(self.app.cwd)  # type: ignore[attr-defined]
        self._apply_input_lock()
        self._refresh_composer_height(False)
        self._render_composer_status()

    def load_bootstrap(self, payload: dict[str, Any]) -> None:
        self._session_candidates = list(payload.get("sessions", []))
        self._model_candidates = [str(item) for item in payload.get("models", [])]
        self._available_commands = [str(item) for item in payload.get("available_commands", [])]
        title = payload.get("session_title")
        if title and self.status_bar is not None:
            self.status_bar.set_session_title(str(title))
        if title and self.welcome_dock is not None:
            self.welcome_dock.set_session_title(str(title))
        mode = payload.get("mode")
        if mode and self.status_bar is not None:
            self.status_bar.set_mode(str(mode))
        if mode and self.welcome_dock is not None:
            self.welcome_dock.set_mode(str(mode))
        model = payload.get("model")
        if model and self.status_bar is not None:
            self.status_bar.set_model(str(model))
        if model and self.welcome_dock is not None:
            self.welcome_dock.set_model(str(model))
        config_values = payload.get("config", {})
        if isinstance(config_values, dict):
            self._config_values = {str(key): str(value) for key, value in config_values.items()}

        hydrated: list[dict[str, Any]] = []
        for event in payload.get("history", []):
            kind = event.get("kind")
            raw_payload = event.get("payload", {})
            if kind == "session_update" and isinstance(raw_payload, dict):
                hydrated.append({"kind": kind, "payload": deserialize_session_update(raw_payload)})
            elif kind == "tui_event" and isinstance(raw_payload, dict):
                hydrated.append({"kind": kind, "payload": raw_payload})
        self.history.replace_events(hydrated)
        self.history_hydrator.hydrate(hydrated)
        self.set_shell_ready(True)
        if hydrated:
            self._mark_activity_started()
        if payload.get("history_truncated") and self.conversation is not None:
            self.conversation.add_system_message(
                "Older session activity was truncated during bootstrap to keep startup responsive.",
                title="History Truncated",
                border_style="#8B6A58",
            )

    async def dispatch_prompt(self, text: str) -> None:
        await self.app.dispatch_prompt(text)  # type: ignore[attr-defined]

    def start_processing(self, label: str) -> None:
        self.spinner_service.start("agent", label)
        self._run_activity_seen = False
        self._start_prompt_watchdog()
        self.set_run_state(RunPhase.STARTING, label, details="Waiting for the first agent event...")
        self._tick_spinner()

    def stop_processing(self) -> None:
        self._cancel_prompt_watchdog()
        self.spinner_service.stop("agent")
        self.display_ledger.complete_turn()
        if self.status_bar is not None:
            self.status_bar.set_spinner("")
        if self.conversation is not None:
            self.conversation.clear_activity()
        self.set_input_locked(False)
        self.set_run_state(RunPhase.IDLE, "Ready", details="")

    def update_queue_depth(self, depth: int) -> None:
        if self.status_bar is not None:
            self.status_bar.set_queue_depth(depth)
        self._render_composer_status()

    def on_user_message_chunk(self, update: UserMessageChunk, *, from_history: bool = False) -> None:
        content = update.content
        if not isinstance(content, TextContentBlock) or self.conversation is None:
            return
        self._mark_activity_started()
        if from_history:
            self.display_ledger.replay("user", content.text)
            self.conversation.add_user_message(content.text)
            return
        if self._pending_remote_user_echoes and self._pending_remote_user_echoes[0] == content.text:
            self._pending_remote_user_echoes.popleft()
            self.display_ledger.replay("user", content.text)
            return
        if self.display_ledger.begin_user_turn(content.text):
            self.conversation.add_user_message(content.text)

    def on_agent_message_chunk(self, update: AgentMessageChunk, *, from_history: bool = False) -> None:
        content = update.content
        if not isinstance(content, TextContentBlock) or self.conversation is None:
            return
        self._mark_activity_started()
        if from_history:
            self.display_ledger.replay("assistant", content.text)
            self.conversation.add_assistant_message(content.text)
            return
        self._mark_run_activity()
        self.set_run_state(RunPhase.STREAMING, "Streaming response")
        if self.display_ledger.allow_assistant_text(content.text):
            self.conversation.add_assistant_message(content.text)

    def on_thought_chunk(self, update: AgentThoughtChunk) -> None:
        content = update.content
        if self.conversation is not None and isinstance(content, TextContentBlock):
            self._mark_activity_started()
            self._mark_run_activity()
            details = content.text.strip()[:120] if content.text.strip() else ""
            self.set_run_state(RunPhase.THINKING, "Thinking", details=details)
            self.conversation.add_thought(content.text)

    def on_tool_call_start(self, update: ToolCallStart) -> None:
        if self.conversation is None:
            return
        self._mark_activity_started()
        self._mark_run_activity()
        self.set_run_state(RunPhase.TOOL_RUNNING, update.title or "Running tool")
        self.conversation.start_tool_call(
            update.tool_call_id,
            update.title or "Tool",
            kind=update.kind or "tool",
            status=update.status or "pending",
            raw_input=getattr(update, "raw_input", None),
        )
        self.spinner_service.start(update.tool_call_id, update.title or "Tool")

    def on_tool_call_progress(self, update: ToolCallProgress) -> None:
        if self.conversation is None:
            return
        output = update.raw_output
        if output is None and update.content:
            output = self.console_buffers.stringify_content(update.content)
        if output is not None:
            text = self.console_buffers.update(update.tool_call_id, str(output))
            preview, truncated = self.console_buffers.preview(update.tool_call_id, fallback=text)
        else:
            preview, truncated = "", False
        self.conversation.update_tool_call(
            update.tool_call_id,
            title=update.title,
            status=update.status,
            raw_input=update.raw_input,
            output_text=preview if truncated else (self.console_buffers.get(update.tool_call_id) or preview),
            truncated=truncated,
        )
        if update.status in {"completed", "failed"}:
            self.spinner_service.stop(update.tool_call_id)
            if update.status == "failed":
                self.set_run_state(
                    RunPhase.ERROR,
                    update.title or "Tool failed",
                    details="The tool reported a failure.",
                )

    def on_plan_update(self, update: AgentPlanUpdate) -> None:
        if self.plan_panel is not None:
            self.plan_panel.set_plan(update)
        if update.entries:
            self._mark_run_activity()
            if self._run_state.phase not in {RunPhase.WAITING_APPROVAL, RunPhase.WAITING_USER}:
                self.set_run_state(RunPhase.PLANNING, "Updating plan")

    def on_mode_update(self, update: CurrentModeUpdate) -> None:
        if self.status_bar is not None:
            self.status_bar.set_mode(update.current_mode_id)
        if self.welcome_dock is not None:
            self.welcome_dock.set_mode(update.current_mode_id)
        self._render_composer_status()

    def on_session_info_update(self, update: SessionInfoUpdate) -> None:
        if self.status_bar is not None and getattr(update, "title", None):
            self.status_bar.set_session_title(update.title)
        if self.welcome_dock is not None and getattr(update, "title", None):
            self.welcome_dock.set_session_title(update.title)

    def on_config_option_update(self, update: ConfigOptionUpdate) -> None:
        self._config_values = {}
        for option in update.config_options:
            root = option.root
            self._config_values[root.id] = str(root.current_value)
            if root.id == "llm_model":
                self._model_candidates = [str(item.value) for item in getattr(root, "options", [])]
                if self.status_bar is not None:
                    self.status_bar.set_model(str(root.current_value))
                if self.welcome_dock is not None:
                    self.welcome_dock.set_model(str(root.current_value))

    def on_available_commands_update(self, update: AvailableCommandsUpdate) -> None:
        self._available_commands = [command.command for command in update.available_commands]

    def on_usage_update(self, update: UsageUpdate) -> None:
        if self.status_bar is not None:
            self.status_bar.set_usage(
                getattr(update, "input_tokens", 0) or 0,
                getattr(update, "output_tokens", 0) or 0,
            )

    def on_tool_group_event(self, payload: dict[str, Any], *, from_history: bool = False) -> None:
        if self.conversation is None:
            return
        title = str(payload.get("title", "Tool group"))
        items = [str(item) for item in payload.get("items", [])]
        if items:
            self._mark_run_activity()
            self.set_run_state(RunPhase.TOOL_RUNNING, title)
            self.conversation.add_tool_group(title, items)

    def on_status_event(self, payload: dict[str, Any]) -> None:
        phase_name = payload.get("phase")
        if phase_name is not None:
            try:
                phase = RunPhase(str(phase_name))
            except ValueError:
                phase = self._run_state.phase
            label = str(payload.get("label", self._run_state.label))
            details = str(payload.get("details", "")) if payload.get("details") else ""
            lock_input = bool(payload.get("lock_input", False))
            if phase is not RunPhase.STARTING or label != "Waiting for agent":
                self._mark_run_activity()
            self.set_run_state(phase, label, lock_input=lock_input, details=details)

        if self.status_bar is not None:
            spinner = str(payload.get("spinner", "")).strip()
            if spinner:
                self.status_bar.set_spinner(spinner)

    def on_notification_event(self, payload: dict[str, Any]) -> None:
        if self.conversation is not None:
            self.conversation.add_system_message(
                str(payload.get("message", "")),
                title=str(payload.get("title", "Notice")),
                border_style="#475569",
            )

    def on_session_metadata_event(self, payload: dict[str, Any]) -> None:
        if self.status_bar is not None and "model" in payload:
            self.status_bar.set_model(str(payload["model"]))
        if self.welcome_dock is not None and "model" in payload:
            self.welcome_dock.set_model(str(payload["model"]))

    @on(SessionUpdateMessage)
    def handle_session_update(self, message: SessionUpdateMessage) -> None:
        self.update_processor.enqueue_session_update(message.update)

    @on(ExtensionNotificationMessage)
    def handle_extension_notification(self, message: ExtensionNotificationMessage) -> None:
        self.update_processor.enqueue_tui_event(message.params)

    @on(ExtensionRequestMessage)
    def handle_extension_request(self, message: ExtensionRequestMessage) -> None:
        if message.method != TUI_INTERRUPT_METHOD:
            if not message.future.done():
                message.future.set_result({})
            return

        async def _resolve() -> None:
            try:
                payload = message.params
                prompt = payload.get("prompt", {})
                prompt_type = str(prompt.get("type", "tool_approval"))
                if prompt_type == "ask_user":
                    result = await self.ask_user_controller.start(prompt)
                elif prompt_type == "plan_review":
                    result = await self.plan_controller.start(prompt)
                else:
                    result = await self.approval_controller.start(prompt)
                if not message.future.done():
                    message.future.set_result(result)
            except Exception as exc:
                if not message.future.done():
                    message.future.set_exception(exc)

        self.run_worker(_resolve(), exclusive=False)

    @on(PermissionRequestMessage)
    def handle_permission_request(self, message: PermissionRequestMessage) -> None:
        from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse

        async def _resolve() -> None:
            prompt = {
                "type": "tool_approval",
                "title": message.tool_call.title or "Tool review",
                "subtitle": message.tool_call.title or "Tool review",
                "tool_name": message.tool_call.title or "tool",
                "tool_args": message.tool_call.raw_input,
                "allowed_decisions": ["approve", "reject"],
                "can_always_allow": True,
            }
            result = await self.approval_controller.start(prompt)
            if message.future.done():
                return
            remember = result.get("remember", {})
            decision = result.get("decision", {})
            if remember.get("type") == "always_allow":
                option_id = next(
                    (option.option_id for option in message.options if "always" in option.option_id),
                    "approve_always",
                )
                message.future.set_result(
                    RequestPermissionResponse(
                        outcome=AllowedOutcome(outcome="selected", option_id=option_id)
                    )
                )
                return
            if decision.get("type") == "approve":
                option_id = next(
                    (option.option_id for option in message.options if "approve" in option.option_id),
                    "approve",
                )
                message.future.set_result(
                    RequestPermissionResponse(
                        outcome=AllowedOutcome(outcome="selected", option_id=option_id)
                    )
                )
                return
            message.future.set_result(
                RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
            )

        self.run_worker(_resolve(), exclusive=False)

    @on(ChatTextArea.Submitted)
    def handle_chat_submitted(self, message: ChatTextArea.Submitted) -> None:
        self.run_worker(self.message_controller.submit(message.text), exclusive=False)

    @on(ChatTextArea.CompletionsChanged)
    def handle_completions_changed(self, message: ChatTextArea.CompletionsChanged) -> None:
        if self.autocomplete_controller is not None:
            self.autocomplete_controller.update(message.items, message.selected)
        self._refresh_composer_height(bool(message.items))

    @on(AutocompletePopup.SelectionRequested)
    def handle_completion_selection_requested(self, message: AutocompletePopup.SelectionRequested) -> None:
        if self.chat_input is None:
            return
        self.chat_input.set_selected_completion(message.index)
        self.chat_input.focus()

    def action_toggle_plan(self) -> None:
        if self.plan_panel is not None:
            self.plan_panel.toggle()

    def action_clear_messages(self) -> None:
        if self.conversation is not None:
            self.conversation.clear_log()
        if self.plan_panel is not None:
            self.plan_panel.clear_plan()
        self._activity_started = False
        self._run_state = RunState()
        self._pending_remote_user_echoes.clear()
        self.set_input_locked(False)
        self._cancel_prompt_watchdog()
        if self.welcome_dock is not None:
            self.welcome_dock.reveal()
        self._render_composer_status()

    def action_jump_to_latest(self) -> None:
        if self.conversation is not None:
            self.conversation.auto_follow = True
            self.conversation.scroll_latest()

    def action_open_command_palette(self) -> None:
        async def _open() -> None:
            commands = [
                (f"/{name}", command.description)
                for name, command in self.app.command_registry.all().items()  # type: ignore[attr-defined]
            ]
            selected = await self.app.push_screen_wait(CommandPaletteScreen(commands))  # type: ignore[attr-defined]
            if selected and self.chat_input is not None:
                self.chat_input.load_text(selected)
                self.chat_input.focus()

        self.run_worker(_open(), exclusive=False)

    def action_open_session_picker(self) -> None:
        async def _open() -> None:
            sessions = await self.app.conn.list_sessions(cwd=self.app.cwd)  # type: ignore[attr-defined]
            items = [
                {
                    "session_id": session.session_id,
                    "title": session.title or f"Session {session.session_id[:8]}",
                    "cwd": session.cwd,
                    "mode": "",
                }
                for session in sessions.sessions
            ]
            selected = await self.app.push_screen_wait(SessionBrowserScreen(items))  # type: ignore[attr-defined]
            if selected == "__new__":
                await self.app.new_session()  # type: ignore[attr-defined]
            elif selected:
                await self.app.resume_session(selected)  # type: ignore[attr-defined]

        self.run_worker(_open(), exclusive=False)

    def _tick_spinner(self) -> None:
        spinner_text = self.spinner_service.next_frame()
        if self.status_bar is not None:
            self.status_bar.set_spinner(spinner_text)
        if self.conversation is not None:
            self.conversation.tick_animations(self.spinner_service.current_symbol())
        self._render_composer_status()

    def _refresh_composer_height(self, expanded: bool) -> None:
        if self.composer is None:
            return
        self.composer.styles.height = 15 if expanded else 6

    def refresh_theme(self) -> None:
        if self.status_bar is not None:
            self.status_bar.refresh_theme()
        if self.welcome_dock is not None:
            self.welcome_dock.refresh_theme()
        if self.conversation is not None:
            self.conversation.refresh_theme()
        if self.plan_panel is not None:
            self.plan_panel.refresh_theme()
        if self.autocomplete_popup is not None:
            self.autocomplete_popup.refresh_theme()
        if self.composer_status is not None:
            self.composer_status.refresh_theme()
        self._render_composer_status()

    @property
    def shell_ready(self) -> bool:
        return self._shell_ready

    @property
    def input_locked(self) -> bool:
        return self._input_locked

    def is_local_command(self, text: str) -> bool:
        registry = getattr(self.app, "command_registry", None)
        return bool(registry and registry.is_command(text))

    def set_shell_ready(self, ready: bool) -> None:
        self._shell_ready = ready
        if self.welcome_dock is not None:
            self.welcome_dock.set_ready(ready)
        self._render_composer_status()

    def set_input_locked(self, locked: bool, reason: str = "") -> None:
        self._input_locked = locked
        self._input_lock_reason = reason
        self._run_state.lock_input = locked
        self._apply_input_lock()
        self._render_composer_status()

    def set_run_state(
        self,
        phase: RunPhase,
        label: str,
        *,
        lock_input: bool | None = None,
        details: str = "",
    ) -> None:
        if lock_input is not None:
            self._input_locked = lock_input
        self._run_state = RunState(
            phase=phase,
            label=label,
            lock_input=self._input_locked,
            details=details,
        )
        self._apply_input_lock()
        if self.conversation is not None:
            if phase is RunPhase.IDLE:
                self.conversation.clear_activity()
            else:
                self.conversation.show_activity(
                    phase=phase,
                    label=label,
                    details=details,
                    frame=self.spinner_service.current_symbol(),
                )
        self._render_composer_status()

    def record_local_submission(self, text: str, *, expect_remote_echo: bool) -> None:
        if not text.strip() or self.conversation is None:
            return
        self._mark_activity_started()
        if expect_remote_echo:
            self._pending_remote_user_echoes.append(text)
            self.display_ledger.replay("user", text)
        else:
            self.display_ledger.begin_user_turn(text)
        self.conversation.add_user_message(text)

    def _mark_activity_started(self) -> None:
        if self._activity_started:
            return
        self._activity_started = True
        if self.conversation is not None:
            self.conversation.set_welcome_message(
                cwd=getattr(self.app, "cwd", str(Path.cwd())),
                session_title=self.status_bar.session_title if self.status_bar is not None else "New Session",
                mode_name=self.status_bar.mode_name if self.status_bar is not None else "accept_edits",
                model_id=self.status_bar.model_id if self.status_bar is not None else "",
                ready=self._shell_ready,
            )
        if self.welcome_dock is not None:
            self.welcome_dock.dismiss()

    def _render_composer_status(self) -> None:
        if self.composer_status is None:
            return
        if self.status_bar is not None:
            self.composer_status.set_mode(self.status_bar.mode_name)
            self.composer_status.set_queue_depth(self.status_bar.queue_depth)
        self.composer_status.set_shell_ready(self._shell_ready)
        self.composer_status.set_state(self._run_state)

    def _apply_input_lock(self) -> None:
        if self.chat_input is not None:
            self.chat_input.disabled = self._input_locked
            if not self._input_locked:
                self.chat_input.focus()
        if self._input_locked and self.autocomplete_controller is not None:
            self.autocomplete_controller.update([], None)
            self._refresh_composer_height(False)

    def _start_prompt_watchdog(self) -> None:
        self._cancel_prompt_watchdog()
        self._prompt_watchdog = asyncio.create_task(self._prompt_start_watchdog())

    def _cancel_prompt_watchdog(self) -> None:
        if self._prompt_watchdog is not None:
            self._prompt_watchdog.cancel()
            self._prompt_watchdog = None

    async def _prompt_start_watchdog(self) -> None:
        try:
            await asyncio.sleep(1.5)
        except asyncio.CancelledError:
            return

        if not self._run_activity_seen and self.message_controller.busy:
            self.set_run_state(
                RunPhase.STARTING,
                self._run_state.label or "Waiting for agent",
                details="Still waiting for the first agent event...",
            )

    def _mark_run_activity(self) -> None:
        self._run_activity_seen = True
        self._cancel_prompt_watchdog()
        if self._run_state.phase is RunPhase.STARTING and self._run_state.details:
            self._run_state.details = ""

    def _build_completions(self, text: str, cursor: int) -> list[CompletionItem]:
        prefix_text = text[:cursor]
        if prefix_text.lstrip().startswith("/"):
            slash_items = self._build_slash_completions(prefix_text)
            if slash_items:
                return slash_items[:24]

        token = prefix_text.split()[-1] if prefix_text.split() else ""
        if token.startswith(".") or token.startswith("/") or "/" in token:
            return self._build_path_completions(token, cursor - len(token), cursor)[:24]
        return []

    def _build_slash_completions(self, prefix_text: str) -> list[CompletionItem]:
        body = prefix_text.lstrip()
        command_offset = len(prefix_text) - len(body)
        command_part, separator, _remainder = body.partition(" ")
        command_name = command_part.lstrip("/")

        if not separator:
            replace_start = command_offset
            replace_end = command_offset + len(command_part)
            items: list[CompletionItem] = []
            for name, command in sorted(self.app.command_registry.all().items()):  # type: ignore[attr-defined]
                if command_name and not name.startswith(command_name):
                    continue
                items.append(
                    CompletionItem(
                        label=f"/{name}",
                        value=f"/{name} ",
                        meta=command.description,
                        replace_start=replace_start,
                        replace_end=replace_end,
                    )
                )
            return items

        arg_text = body[len(command_part) :]
        args = arg_text.split()
        trailing_space = prefix_text.endswith(" ")
        current_fragment = "" if trailing_space else (args[-1] if args else "")
        current_index = len(args) if trailing_space else max(len(args) - 1, 0)
        replace_end = len(prefix_text)
        replace_start = replace_end - len(current_fragment)

        if command_name == "mode":
            return self._build_mode_completions(current_fragment, replace_start, replace_end)
        if command_name == "model" and current_index == 0:
            return self._build_model_completions(current_fragment, replace_start, replace_end)
        if command_name == "session":
            return self._build_session_completions(args, current_index, current_fragment, replace_start, replace_end)
        if command_name == "config" and current_index == 0:
            return self._build_config_completions(current_fragment, replace_start, replace_end)
        if current_fragment.startswith(".") or current_fragment.startswith("/") or "/" in current_fragment:
            return self._build_path_completions(current_fragment, replace_start, replace_end)
        return []

    def _build_mode_completions(
        self,
        fragment: str,
        replace_start: int,
        replace_end: int,
    ) -> list[CompletionItem]:
        items: list[CompletionItem] = []
        lowered = fragment.lower()
        for mode in self._mode_candidates:
            mode_id = mode["id"]
            if lowered and not mode_id.startswith(lowered):
                continue
            items.append(
                CompletionItem(
                    label=mode_id,
                    value=f"{mode_id} ",
                    meta=mode["description"],
                    replace_start=replace_start,
                    replace_end=replace_end,
                )
            )
        return items

    def _build_model_completions(
        self,
        fragment: str,
        replace_start: int,
        replace_end: int,
    ) -> list[CompletionItem]:
        return [
            CompletionItem(
                label=model,
                value=f"{model} ",
                meta="model",
                replace_start=replace_start,
                replace_end=replace_end,
            )
            for model in self._model_candidates
            if not fragment or model.startswith(fragment)
        ]

    @property
    def model_candidates(self) -> list[str]:
        return list(self._model_candidates)

    def _build_session_completions(
        self,
        args: list[str],
        current_index: int,
        fragment: str,
        replace_start: int,
        replace_end: int,
    ) -> list[CompletionItem]:
        if current_index == 0:
            subcommands = {
                "list": "browse saved sessions",
                "new": "start a fresh session",
                "resume": "resume an existing session",
                "fork": "branch from the current session",
            }
            return [
                CompletionItem(
                    label=name,
                    value=f"{name} ",
                    meta=description,
                    replace_start=replace_start,
                    replace_end=replace_end,
                )
                for name, description in subcommands.items()
                if not fragment or name.startswith(fragment)
            ]
        if args and args[0] == "resume" and current_index == 1:
            items: list[CompletionItem] = []
            for session in self._session_candidates:
                session_id = str(session.get("session_id", ""))
                title = str(session.get("title", "")) or "session"
                if fragment and not session_id.startswith(fragment):
                    continue
                items.append(
                    CompletionItem(
                        label=session_id,
                        value=f"{session_id} ",
                        meta=title,
                        replace_start=replace_start,
                        replace_end=replace_end,
                    )
                )
            return items
        return []

    def _build_config_completions(
        self,
        fragment: str,
        replace_start: int,
        replace_end: int,
    ) -> list[CompletionItem]:
        return [
            CompletionItem(
                label=key,
                value=f"{key} ",
                meta=str(value),
                replace_start=replace_start,
                replace_end=replace_end,
            )
            for key, value in sorted(self._config_values.items())
            if not fragment or key.startswith(fragment)
        ]

    def _build_path_completions(
        self,
        token: str,
        replace_start: int,
        replace_end: int,
    ) -> list[CompletionItem]:
        base = Path(self.app.cwd)  # type: ignore[attr-defined]
        stem = token.replace('"', "")
        parent = (base / stem).parent if stem else base
        prefix = (base / stem).name
        items: list[CompletionItem] = []
        if not parent.exists():
            return items
        for path in sorted(parent.iterdir())[:20]:
            candidate = path.name
            if prefix and not candidate.startswith(prefix):
                continue
            value = str((Path(stem).parent / candidate).as_posix())
            if path.is_dir():
                value = f"{value}/"
            items.append(
                CompletionItem(
                    label=value,
                    value=value,
                    meta="path",
                    replace_start=replace_start,
                    replace_end=replace_end,
                )
            )
        return items
