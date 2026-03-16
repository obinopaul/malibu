"""ACP agent implementation backing Malibu's Textual shell."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from acp import (
    Agent as ACPAgent,
    text_block,
    tool_content,
    update_agent_message,
    update_tool_call,
)
from acp.exceptions import RequestError
from acp.schema import (
    AgentCapabilities,
    AgentPlanUpdate,
    AudioContentBlock,
    AuthenticateResponse,
    ClientCapabilities,
    ConfigOptionUpdate,
    CurrentModeUpdate,
    EmbeddedResourceContentBlock,
    ForkSessionResponse,
    HttpMcpServer,
    ImageContentBlock,
    Implementation,
    InitializeResponse,
    ListSessionsResponse,
    LoadSessionResponse,
    McpServerStdio,
    NewSessionResponse,
    PermissionOption,
    PromptCapabilities,
    PromptResponse,
    ResourceContentBlock,
    ResumeSessionResponse,
    SessionInfo,
    SessionInfoUpdate,
    SetSessionConfigOptionResponse,
    SetSessionModelResponse,
    SetSessionModeResponse,
    SseMcpServer,
    TextContentBlock,
    ToolCallProgress,
    ToolCallUpdate,
    UsageUpdate,
    UserMessageChunk,
)
from langgraph.types import Command

from malibu.agent.compaction import CompactionManager
from malibu.agent.modes import DEFAULT_MODES
from malibu.config import Settings
from malibu.server.auth import ServerAuthHandler
from malibu.server.config_options import ConfigOptionManager
from malibu.server.content import convert_any_block
from malibu.server.extensions import ExtensionRegistry
from malibu.server.permissions import PermissionManager
from malibu.server.plans import build_empty_plan, build_plan_update, format_plan_text
from malibu.server.sessions import SessionManager
from malibu.server.streaming import ToolCallAccumulator, create_tool_call_start, format_execute_result
from malibu.telemetry.logging import get_logger
from malibu.tui.protocol import TUI_BOOTSTRAP_METHOD, TUI_EVENT_NOTIFICATION, TUI_INTERRUPT_METHOD, build_tui_event

if TYPE_CHECKING:
    from acp.interfaces import Client

log = get_logger(__name__)


class MalibuAgent(ACPAgent):
    """Malibu ACP agent with custom TUI interrupt and bootstrap support."""

    _conn: Client

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._session_mgr = SessionManager(settings)
        self._permissions = PermissionManager()
        self._config_options = ConfigOptionManager()
        self._auth_handler = ServerAuthHandler(settings)
        self._extensions = ExtensionRegistry()
        self._cancelled: dict[str, bool] = {}
        self._compaction_mgr = CompactionManager()

        self._extensions.register_method("compact", self._ext_compact)
        self._extensions.register_method("plan", self._ext_plan)
        self._extensions.register_method("skills", self._ext_skills)
        self._extensions.register_method(TUI_BOOTSTRAP_METHOD, self._ext_tui_bootstrap)

    def on_connect(self, conn: Client) -> None:
        self._conn = conn
        log.info("client_connected")

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        return InitializeResponse(
            protocol_version=protocol_version,
            agent_capabilities=AgentCapabilities(prompt_capabilities=PromptCapabilities(image=True)),
        )

    async def new_session(
        self,
        cwd: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        session_id = uuid4().hex
        self._session_mgr.register_session(session_id, cwd=cwd, mode_id=DEFAULT_MODES.current_mode_id)
        return NewSessionResponse(session_id=session_id, modes=DEFAULT_MODES)

    async def load_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> LoadSessionResponse | None:
        self._session_mgr.register_session(session_id, cwd=cwd)
        return LoadSessionResponse(modes=DEFAULT_MODES)

    async def list_sessions(
        self,
        cursor: str | None = None,
        cwd: str | None = None,
        **kwargs: Any,
    ) -> ListSessionsResponse:
        sessions: list[SessionInfo] = []
        records = []
        if hasattr(self._session_mgr, "list_session_records"):
            records = self._session_mgr.list_session_records(cwd=cwd)
        if isinstance(records, list) and records:
            for record in records:
                sessions.append(
                    SessionInfo(
                        session_id=str(record.get("session_id", "")),
                        cwd=str(record.get("cwd", cwd or ".")),
                        title=str(record.get("title", "Session")),
                    )
                )
        else:
            for session_id in getattr(self._session_mgr, "_agents", {}):
                session_cwd = self._session_mgr.get_cwd(session_id)
                if cwd and session_cwd != cwd:
                    continue
                sessions.append(
                    SessionInfo(
                        session_id=session_id,
                        cwd=session_cwd,
                        title=f"Session {session_id[:8]}",
                    )
                )
        return ListSessionsResponse(sessions=sessions)

    async def set_session_mode(
        self,
        mode_id: str,
        session_id: str,
        **kwargs: Any,
    ) -> SetSessionModeResponse | None:
        self._session_mgr.set_mode(session_id, mode_id)
        await self._emit_session_update(
            session_id,
            CurrentModeUpdate(session_update="current_mode_update", current_mode_id=mode_id),
        )
        return SetSessionModeResponse()

    async def set_session_model(
        self,
        model_id: str,
        session_id: str,
        **kwargs: Any,
    ) -> SetSessionModelResponse | None:
        self._session_mgr.set_model(session_id, model_id)
        await self._emit_tui_event(
            session_id,
            "session_metadata",
            {"model": model_id},
        )
        return SetSessionModelResponse()

    async def set_config_option(
        self,
        config_id: str,
        session_id: str,
        value: str,
        **kwargs: Any,
    ) -> SetSessionConfigOptionResponse | None:
        update = self._config_options.set_option(session_id, config_id, value)
        if update is not None:
            self._session_mgr.update_config(session_id, config_id, update.value)
            config_options = self._config_options.build_session_config_options(session_id)
            await self._emit_session_update(
                session_id,
                ConfigOptionUpdate(session_update="config_option_update", config_options=config_options),
            )
            return SetSessionConfigOptionResponse(config_options=config_options)
        config_options = self._config_options.build_session_config_options(session_id)
        return SetSessionConfigOptionResponse(config_options=config_options)

    async def authenticate(self, method_id: str, **kwargs: Any) -> AuthenticateResponse | None:
        return await self._auth_handler.authenticate(method_id, **kwargs)

    async def prompt(
        self,
        prompt: list[
            TextContentBlock | ImageContentBlock | AudioContentBlock | ResourceContentBlock | EmbeddedResourceContentBlock
        ],
        session_id: str,
        **kwargs: Any,
    ) -> PromptResponse:
        cwd = self._session_mgr.get_cwd(session_id)
        self._cancelled[session_id] = False

        user_text = self._extract_prompt_text(prompt)
        if user_text:
            await self._emit_session_update(
                session_id,
                UserMessageChunk(
                    session_update="user_message_chunk",
                    content=TextContentBlock(type="text", text=user_text),
                ),
            )
            self._maybe_set_session_title(session_id, user_text)

        agent_ready = self._session_mgr.get_agent(session_id) is not None
        await self._emit_status(
            session_id,
            "starting",
            "Dispatching prompt" if agent_ready else "Preparing agent",
            details=(
                "Running the prompt with the warmed session."
                if agent_ready
                else "Loading model, tools, and session state before the first response."
            ),
        )
        agent = self._session_mgr.get_or_create_agent(session_id, cwd=cwd)

        content_blocks: list[dict[str, Any]] = []
        for block in prompt:
            content_blocks.extend(convert_any_block(block, root_dir=cwd))

        config: dict[str, Any] = {"configurable": {"thread_id": session_id}}
        callbacks = self._session_mgr.get_callbacks(session_id)
        if callbacks:
            config["callbacks"] = callbacks

        accumulator = ToolCallAccumulator()
        current_state = None
        resume_payload: Any | None = None

        await self._emit_status(
            session_id,
            "starting",
            "Waiting for agent",
            details="Waiting for the first agent event...",
        )

        try:
            return await self._prompt_loop(
                agent=agent,
                session_id=session_id,
                content_blocks=content_blocks,
                config=config,
                accumulator=accumulator,
                resume_payload=resume_payload,
                current_state=current_state,
            )
        except RequestError as exc:
            await self._emit_status(
                session_id,
                "error",
                "Agent error",
                details=str(exc),
            )
            raise
        except Exception as exc:
            log.error("prompt_error", session_id=session_id, error=str(exc))
            await self._emit_status(
                session_id,
                "error",
                "Agent error",
                details=str(exc),
            )
            raise RequestError(-32603, f"Agent error: {exc}") from exc
        finally:
            self._session_mgr.flush_session(session_id)

    async def _prompt_loop(
        self,
        *,
        agent: Any,
        session_id: str,
        content_blocks: list[dict[str, Any]],
        config: dict[str, Any],
        accumulator: ToolCallAccumulator,
        resume_payload: Any | None,
        current_state: Any,
    ) -> PromptResponse:
        while current_state is None or current_state.interrupts:
            if self._cancelled.pop(session_id, False):
                await self._emit_status(
                    session_id,
                    "cancelled",
                    "Run cancelled",
                    details="The current run was cancelled.",
                )
                return PromptResponse(stop_reason="cancelled")

            input_data = (
                Command(resume=resume_payload)
                if resume_payload is not None
                else {"messages": [{"role": "user", "content": content_blocks}]}
            )
            resume_payload = None

            async for stream_chunk in agent.astream(
                input_data,
                config=config,
                stream_mode=["messages", "updates"],
                subgraphs=True,
            ):
                if not isinstance(stream_chunk, tuple) or len(stream_chunk) != 3:
                    continue

                namespace, stream_mode, data = stream_chunk
                if self._cancelled.pop(session_id, False):
                    await self._emit_status(
                        session_id,
                        "cancelled",
                        "Run cancelled",
                        details="The current run was cancelled.",
                    )
                    return PromptResponse(stop_reason="cancelled")

                if stream_mode == "updates":
                    updates = data
                    if isinstance(updates, dict) and "__interrupt__" in updates:
                        current_state = await agent.aget_state(config)
                        resume_payload = await self._handle_interrupts(current_state=current_state, session_id=session_id)
                        break

                    for node_name, update in (updates.items() if isinstance(updates, dict) else []):
                        if node_name == "tools" and isinstance(update, dict) and "todos" in update:
                            todos = update.get("todos", [])
                            if todos:
                                await self._emit_status(
                                    session_id,
                                    "planning",
                                    "Updating plan",
                                )
                                await self._emit_session_update(session_id, build_plan_update(todos))
                    continue

                message_chunk, _metadata = data
                new_starts = accumulator.process_chunk(message_chunk)
                for tool_start in new_starts:
                    await self._emit_status(
                        session_id,
                        "tool_running",
                        tool_start.title or "Running tool",
                    )
                    await self._emit_session_update(session_id, tool_start)
                    info = accumulator.active.get(tool_start.tool_call_id, {})
                    if info.get("name") == "write_todos":
                        todos = info.get("args", {}).get("todos", [])
                        if todos:
                            await self._emit_session_update(session_id, build_plan_update(todos))

                if hasattr(message_chunk, "type") and message_chunk.type == "tool":
                    tool_call_id = getattr(message_chunk, "tool_call_id", None)
                    if tool_call_id and tool_call_id in accumulator.active:
                        info = accumulator.active[tool_call_id]
                        if info.get("name") != "edit_file":
                            content = getattr(message_chunk, "content", "")
                            if info.get("name") == "execute":
                                command = info.get("args", {}).get("command", "")
                                formatted = format_execute_result(command, str(content))
                            else:
                                formatted = str(content)
                            await self._emit_session_update(
                                session_id,
                                update_tool_call(
                                    tool_call_id=tool_call_id,
                                    status="completed",
                                    content=[tool_content(text_block(formatted))],
                                ),
                            )
                elif isinstance(message_chunk, str):
                    if not namespace:
                        await self._send_text(session_id, message_chunk)
                elif hasattr(message_chunk, "content") and message_chunk.content:
                    text = self._extract_text(message_chunk.content)
                    if text and not namespace:
                        await self._send_text(session_id, text)

            current_state = await agent.aget_state(config)

        self._cancelled.pop(session_id, None)
        await self._emit_status(session_id, "idle", "Ready")
        return PromptResponse(stop_reason="end_turn")

    async def fork_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> ForkSessionResponse:
        new_session_id = uuid4().hex
        self._session_mgr.fork_session(session_id, new_session_id, cwd=cwd)
        return ForkSessionResponse(session_id=new_session_id, modes=DEFAULT_MODES)

    async def resume_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> ResumeSessionResponse:
        self._session_mgr.register_session(session_id, cwd=cwd)
        return ResumeSessionResponse(modes=DEFAULT_MODES)

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        self._cancelled[session_id] = True
        await self._emit_status(
            session_id,
            "cancelled",
            "Cancelling run",
            details="The current run is being cancelled.",
        )

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return await self._extensions.handle_method(method, params)

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        await self._extensions.handle_notification(method, params)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _emit_session_update(self, session_id: str, update: Any) -> None:
        self._session_mgr.record_session_update(session_id, update)
        await self._conn.session_update(session_id=session_id, update=update, source="Malibu")

    async def _emit_tui_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        record: bool = True,
    ) -> None:
        params = build_tui_event(session_id, event_type, payload)
        if record:
            self._session_mgr.record_tui_event(session_id, params)
        try:
            await self._conn.ext_notification(TUI_EVENT_NOTIFICATION, params)
        except Exception:
            pass

    async def _emit_status(
        self,
        session_id: str,
        phase: str,
        label: str,
        *,
        lock_input: bool = False,
        details: str = "",
    ) -> None:
        await self._emit_tui_event(
            session_id,
            "status",
            {
                "phase": phase,
                "label": label,
                "lock_input": lock_input,
                "details": details,
            },
            record=False,
        )

    async def _send_text(self, session_id: str, text: str) -> None:
        await self._emit_session_update(session_id, update_agent_message(text_block(text)))

    async def _handle_interrupts(self, *, current_state: Any, session_id: str) -> Any:
        if not (current_state.next and current_state.interrupts):
            return None

        for interrupt in current_state.interrupts:
            value = interrupt.value
            if isinstance(value, dict) and value.get("type") == "ask_user":
                await self._emit_status(
                    session_id,
                    "waiting_user",
                    "User input required",
                    lock_input=True,
                    details="Answer the active question to continue.",
                )
                response = await self._conn.ext_method(
                    TUI_INTERRUPT_METHOD,
                    {
                        "session_id": session_id,
                        "interrupt_id": interrupt.id,
                        "prompt": {
                            "type": "ask_user",
                            "questions": value.get("questions", []),
                            "tool_call_id": value.get("tool_call_id"),
                        },
                    },
                )
                await self._emit_status(
                    session_id,
                    "starting",
                    "Resuming run",
                    details="Processing your answers.",
                )
                return response

            if not isinstance(value, dict):
                raise RequestError(-32600, "Unsupported interrupt payload", {"interrupt_value": value})

            action_requests = value.get("action_requests", [])
            review_configs = value.get("review_configs", [])
            decisions: list[dict[str, Any]] = []
            prompted = False

            for index, action in enumerate(action_requests):
                tool_name = action.get("name", "tool")
                tool_args = action.get("args", {})
                review_config = review_configs[index] if index < len(review_configs) else {}
                allowed_decisions = list(review_config.get("allowed_decisions", ["approve", "reject"]))

                if self._permissions.is_auto_approved(session_id, tool_name, tool_args):
                    decisions.append({"type": "approve"})
                    continue

                if tool_name == "write_todos":
                    todos = tool_args.get("todos", [])
                    await self._send_text(session_id, format_plan_text(todos))
                    await self._emit_status(
                        session_id,
                        "waiting_approval",
                        "Review plan",
                        lock_input=True,
                        details="Approve the proposed plan or request a revision.",
                    )
                    prompt = {
                        "type": "plan_review",
                        "title": "Review plan",
                        "tool_name": tool_name,
                        "todos": todos,
                        "allowed_decisions": ["approve", "reject"],
                        "can_always_allow": True,
                    }
                else:
                    prompt = {
                        "type": "tool_approval",
                        "title": self._permissions.build_title(tool_name, tool_args),
                        "subtitle": tool_name,
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                        "allowed_decisions": allowed_decisions,
                        "can_always_allow": True,
                        "cwd": self._session_mgr.get_cwd(session_id),
                    }
                    await self._emit_status(
                        session_id,
                        "waiting_approval",
                        str(prompt["title"]),
                        lock_input=True,
                        details=f"{tool_name} needs approval before Malibu can continue.",
                    )

                prompted = True
                response = await self._conn.ext_method(
                    TUI_INTERRUPT_METHOD,
                    {
                        "session_id": session_id,
                        "interrupt_id": interrupt.id,
                        "prompt": prompt,
                    },
                )

                decision = response.get("decision", {"type": "approve"})
                remember = response.get("remember", {})
                if remember.get("type") == "always_allow":
                    self._permissions.register_always_allow(session_id, tool_name, tool_args)

                if tool_name == "write_todos":
                    if decision.get("type") == "approve":
                        self._permissions.approve_plan(session_id, tool_args)
                    elif decision.get("type") == "reject":
                        self._permissions.clear_plan(session_id)
                        await self._emit_session_update(session_id, build_empty_plan())

                decisions.append(decision)

            if prompted:
                await self._emit_status(
                    session_id,
                    "starting",
                    "Resuming run",
                    details="Processing the approval response.",
                )
            return {"decisions": decisions}

        return None

    @staticmethod
    def _extract_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "".join(parts)
        return str(content)

    @staticmethod
    def _extract_prompt_text(
        prompt: list[
            TextContentBlock | ImageContentBlock | AudioContentBlock | ResourceContentBlock | EmbeddedResourceContentBlock
        ],
    ) -> str:
        parts: list[str] = []
        for block in prompt:
            if isinstance(block, TextContentBlock):
                parts.append(block.text)
        return "\n".join(part for part in parts if part).strip()

    def _maybe_set_session_title(self, session_id: str, user_text: str) -> None:
        existing = self._session_mgr.get_bootstrap_payload(session_id).get("session_title", "")
        if existing and not str(existing).startswith("Session "):
            return
        title = user_text.splitlines()[0].strip()[:72]
        if not title:
            return
        self._session_mgr.set_title(session_id, title)

    # ------------------------------------------------------------------
    # Extension methods
    # ------------------------------------------------------------------

    async def _ext_tui_bootstrap(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = params.get("session_id", "")
        cwd = params.get("cwd", ".")
        if not session_id:
            raise RequestError(-32602, "session_id is required")
        self._session_mgr.warm_session(session_id, cwd=cwd)
        payload = self._session_mgr.get_bootstrap_payload(session_id)
        payload["sessions"] = self._session_mgr.list_session_summaries(cwd=cwd)
        payload["models"] = [self._session_mgr.get_model(session_id)]
        payload["available_commands"] = []
        return payload

    async def _ext_compact(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = params.get("session_id", "")
        if not session_id:
            raise RequestError(-32602, "session_id is required")
        agent = self._session_mgr.get_agent(session_id)
        if agent is None:
            raise RequestError(-32602, f"No agent for session {session_id}")
        await self._compaction_mgr.compact_state(agent, session_id, self._settings)
        await self._send_text(session_id, "[Context compacted — older messages summarised.]")
        return {"status": "compacted"}

    async def _ext_plan(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = params.get("session_id", "")
        task = params.get("task", "")
        if not session_id:
            raise RequestError(-32602, "session_id is required")
        if not task:
            raise RequestError(-32602, "task is required")
        raise RequestError(
            -32601,
            "Planning subagent is now natively integrated via deep agents. Ask the agent directly.",
        )

    async def _ext_skills(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = params.get("session_id", "")
        action = params.get("action", "list")
        skill_name = params.get("skill_name")
        if not session_id:
            raise RequestError(-32602, "session_id is required")
        registry = self._session_mgr.skill_registry
        if action == "info" and skill_name:
            skill = registry.get_skill(skill_name)
            if skill:
                return {
                    "skill": {
                        "name": skill["name"],
                        "description": skill["description"],
                        "source": skill.get("source", "unknown"),
                        "instructions": skill.get("instructions", ""),
                    }
                }
            return {"skill": None}
        return {"skills": registry.list_skills()}
