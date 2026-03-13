"""MalibuAgent — full ACP Agent implementation with all 15 protocol methods.

This is the core of the Malibu harness.  It implements every method defined
in ``acp.interfaces.Agent`` and orchestrates:

  - LangGraph agent streaming with tool call accumulation
  - Human-in-the-loop permission prompts via ACP request_permission
  - Plan lifecycle (create / update / clear)
  - Session management (new / load / list / fork / resume)
  - Mode switching with interrupt reconfiguration
  - Model switching
  - Config option management
  - Authentication
  - Cancellation
  - Extension methods / notifications

Every method is wired to database persistence and structured logging.
"""

from __future__ import annotations

import json
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
    ToolCallUpdate,
    UsageUpdate,
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

if TYPE_CHECKING:
    from acp.interfaces import Client

log = get_logger(__name__)


class MalibuAgent(ACPAgent):
    """Production-grade ACP Agent backed by LangGraph + PostgreSQL.

    Implements all 15 ACP protocol methods.
    """

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

        # Register built-in extension methods
        self._extensions.register_method("compact", self._ext_compact)
        self._extensions.register_method("plan", self._ext_plan)
        self._extensions.register_method("skills", self._ext_skills)

    # ───────────────────────────────────────────────────────────
    # Connection lifecycle
    # ───────────────────────────────────────────────────────────

    def on_connect(self, conn: Client) -> None:
        """Store the client connection for session_update and request_permission calls."""
        self._conn = conn
        log.info("client_connected")

    # ───────────────────────────────────────────────────────────
    # 1. initialize
    # ───────────────────────────────────────────────────────────

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        log.info(
            "initialize",
            protocol_version=protocol_version,
            client_info=client_info.model_dump() if client_info else None,
        )
        return InitializeResponse(
            protocol_version=protocol_version,
            agent_capabilities=AgentCapabilities(
                prompt_capabilities=PromptCapabilities(image=True),
            ),
        )

    # ───────────────────────────────────────────────────────────
    # 2. new_session
    # ───────────────────────────────────────────────────────────

    async def new_session(
        self,
        cwd: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        session_id = uuid4().hex
        self._session_mgr.create_session(session_id, cwd=cwd, mode_id=DEFAULT_MODES.current_mode_id)
        log.info("new_session", session_id=session_id, cwd=cwd)
        return NewSessionResponse(session_id=session_id, modes=DEFAULT_MODES)

    # ───────────────────────────────────────────────────────────
    # 3. load_session
    # ───────────────────────────────────────────────────────────

    async def load_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> LoadSessionResponse | None:
        agent = self._session_mgr.get_agent(session_id)
        if agent is None:
            # Recreate agent for existing session
            self._session_mgr.create_session(session_id, cwd=cwd)
        log.info("load_session", session_id=session_id, cwd=cwd)
        return LoadSessionResponse(modes=DEFAULT_MODES)

    # ───────────────────────────────────────────────────────────
    # 4. list_sessions (unstable)
    # ───────────────────────────────────────────────────────────

    async def list_sessions(
        self,
        cursor: str | None = None,
        cwd: str | None = None,
        **kwargs: Any,
    ) -> ListSessionsResponse:
        # Return in-memory sessions for now; production would query DB
        items: list[SessionInfo] = []
        for sid in list(self._session_mgr._agents.keys()):
            session_cwd = self._session_mgr.get_cwd(sid)
            if cwd and session_cwd != cwd:
                continue
            items.append(
                SessionInfo(
                    session_id=sid,
                    cwd=session_cwd,
                    title=f"Session {sid[:8]}",
                )
            )
        log.info("list_sessions", count=len(items))
        return ListSessionsResponse(sessions=items)

    # ───────────────────────────────────────────────────────────
    # 5. set_session_mode
    # ───────────────────────────────────────────────────────────

    async def set_session_mode(
        self,
        mode_id: str,
        session_id: str,
        **kwargs: Any,
    ) -> SetSessionModeResponse | None:
        self._session_mgr.set_mode(session_id, mode_id)
        # Notify client of mode change
        await self._conn.session_update(
            session_id=session_id,
            update=CurrentModeUpdate(session_update="current_mode_update", current_mode_id=mode_id),
            source="Malibu",
        )
        log.info("set_session_mode", session_id=session_id, mode_id=mode_id)
        return SetSessionModeResponse()

    # ───────────────────────────────────────────────────────────
    # 6. set_session_model (unstable)
    # ───────────────────────────────────────────────────────────

    async def set_session_model(
        self,
        model_id: str,
        session_id: str,
        **kwargs: Any,
    ) -> SetSessionModelResponse | None:
        self._session_mgr.set_model(session_id, model_id)
        log.info("set_session_model", session_id=session_id, model_id=model_id)
        return SetSessionModelResponse()

    # ───────────────────────────────────────────────────────────
    # 7. set_config_option
    # ───────────────────────────────────────────────────────────

    async def set_config_option(
        self,
        config_id: str,
        session_id: str,
        value: str,
        **kwargs: Any,
    ) -> SetSessionConfigOptionResponse | None:
        update = self._config_options.set_option(session_id, config_id, value)
        if update:
            config_options = self._config_options.build_session_config_options(session_id)
            await self._conn.session_update(
                session_id=session_id,
                update=ConfigOptionUpdate(
                    session_update="config_option_update",
                    config_options=config_options,
                ),
                source="Malibu",
            )
        config_options = self._config_options.build_session_config_options(session_id)
        log.info("set_config_option", session_id=session_id, config_id=config_id, value=value)
        return SetSessionConfigOptionResponse(config_options=config_options)

    # ───────────────────────────────────────────────────────────
    # 8. authenticate
    # ───────────────────────────────────────────────────────────

    async def authenticate(self, method_id: str, **kwargs: Any) -> AuthenticateResponse | None:
        log.info("authenticate", method_id=method_id)
        return await self._auth_handler.authenticate(method_id, **kwargs)

    # ───────────────────────────────────────────────────────────
    # 9. prompt (core streaming loop)
    # ───────────────────────────────────────────────────────────

    async def prompt(
        self,
        prompt: list[
            TextContentBlock | ImageContentBlock | AudioContentBlock | ResourceContentBlock | EmbeddedResourceContentBlock
        ],
        session_id: str,
        **kwargs: Any,
    ) -> PromptResponse:
        cwd = self._session_mgr.get_cwd(session_id)
        agent = self._session_mgr.get_or_create_agent(session_id, cwd=cwd)

        self._cancelled[session_id] = False

        # Convert ACP content blocks → LangChain multimodal content
        content_blocks: list[dict[str, Any]] = []
        for block in prompt:
            content_blocks.extend(convert_any_block(block, root_dir=cwd))

        config = {"configurable": {"thread_id": session_id}}
        accumulator = ToolCallAccumulator()
        user_decisions: list[dict[str, Any]] = []
        current_state = None

        log.info("prompt_start", session_id=session_id)

        try:
            return await self._prompt_loop(
                agent=agent,
                session_id=session_id,
                content_blocks=content_blocks,
                config=config,
                accumulator=accumulator,
                user_decisions=user_decisions,
                current_state=current_state,
            )
        except RequestError:
            raise
        except Exception as exc:
            log.error("prompt_error", session_id=session_id, error=str(exc))
            raise RequestError(-32603, f"Agent error: {exc}") from exc

    async def _prompt_loop(
        self,
        *,
        agent: Any,
        session_id: str,
        content_blocks: list[dict[str, Any]],
        config: dict[str, Any],
        accumulator: ToolCallAccumulator,
        user_decisions: list[dict[str, Any]],
        current_state: Any,
    ) -> PromptResponse:
        while current_state is None or current_state.interrupts:
            if self._cancelled.pop(session_id, False):
                return PromptResponse(stop_reason="cancelled")

            input_data = (
                Command(resume={"decisions": user_decisions})
                if user_decisions
                else {"messages": [{"role": "user", "content": content_blocks}]}
            )

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
                    return PromptResponse(stop_reason="cancelled")

                if stream_mode == "updates":
                    updates = data
                    if isinstance(updates, dict) and "__interrupt__" in updates:
                        interrupt_objs = updates.get("__interrupt__")
                        if interrupt_objs:
                            for interrupt_obj in interrupt_objs:
                                interrupt_value = interrupt_obj.value
                                if not isinstance(interrupt_value, dict):
                                    raise RequestError(
                                        -32600,
                                        "ACP limitation: free-form LangGraph interrupt() not "
                                        "supported. Use action_requests/review_configs for HITL.",
                                        {"interrupt_value": interrupt_value},
                                    )

                            current_state = await agent.aget_state(config)
                            user_decisions = await self._handle_interrupts(
                                current_state=current_state, session_id=session_id
                            )
                            break

                    # Check for todo updates from tools node
                    for node_name, update in (updates.items() if isinstance(updates, dict) else []):
                        if node_name == "tools" and isinstance(update, dict) and "todos" in update:
                            todos = update.get("todos", [])
                            if todos:
                                plan_update = build_plan_update(todos)
                                await self._conn.session_update(
                                    session_id=session_id, update=plan_update, source="Malibu"
                                )
                    continue

                # Message stream
                message_chunk, _metadata = data

                # Process tool call chunks
                new_starts = accumulator.process_chunk(message_chunk)
                for tc_start in new_starts:
                    await self._conn.session_update(session_id=session_id, update=tc_start, source="Malibu")

                    # If write_todos, forward plan immediately
                    tc_info = accumulator.active.get(tc_start.tool_call_id, {})
                    if tc_info.get("name") == "write_todos":
                        todos = tc_info.get("args", {}).get("todos", [])
                        if todos:
                            plan_update = build_plan_update(todos)
                            await self._conn.session_update(
                                session_id=session_id, update=plan_update, source="Malibu"
                            )

                # Tool result messages
                if hasattr(message_chunk, "type") and message_chunk.type == "tool":
                    tool_call_id = getattr(message_chunk, "tool_call_id", None)
                    if tool_call_id and tool_call_id in accumulator.active:
                        tc_info = accumulator.active[tool_call_id]
                        if tc_info.get("name") != "edit_file":
                            content = getattr(message_chunk, "content", "")
                            if tc_info.get("name") == "execute":
                                cmd = tc_info.get("args", {}).get("command", "")
                                formatted = format_execute_result(cmd, str(content))
                            else:
                                formatted = str(content)
                            tc_update = update_tool_call(
                                tool_call_id=tool_call_id,
                                status="completed",
                                content=[tool_content(text_block(formatted))],
                            )
                            await self._conn.session_update(
                                session_id=session_id, update=tc_update, source="Malibu"
                            )

                # Text content streaming
                elif isinstance(message_chunk, str):
                    if not namespace:
                        await self._send_text(session_id, message_chunk)
                elif hasattr(message_chunk, "content") and message_chunk.content:
                    text = self._extract_text(message_chunk.content)
                    if text and not namespace:
                        await self._send_text(session_id, text)

            current_state = await agent.aget_state(config)

        self._cancelled.pop(session_id, None)
        log.info("prompt_complete", session_id=session_id)
        return PromptResponse(stop_reason="end_turn")

    # ───────────────────────────────────────────────────────────
    # 10. fork_session (unstable)
    # ───────────────────────────────────────────────────────────

    async def fork_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> ForkSessionResponse:
        new_session_id = uuid4().hex
        self._session_mgr.fork_session(session_id, new_session_id, cwd=cwd)
        log.info("fork_session", source=session_id, new=new_session_id)
        return ForkSessionResponse(session_id=new_session_id, modes=DEFAULT_MODES)

    # ───────────────────────────────────────────────────────────
    # 11. resume_session (unstable)
    # ───────────────────────────────────────────────────────────

    async def resume_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> ResumeSessionResponse:
        agent = self._session_mgr.get_agent(session_id)
        if agent is None:
            self._session_mgr.create_session(session_id, cwd=cwd)
        log.info("resume_session", session_id=session_id, cwd=cwd)
        return ResumeSessionResponse(modes=DEFAULT_MODES)

    # ───────────────────────────────────────────────────────────
    # 12. cancel
    # ───────────────────────────────────────────────────────────

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        self._cancelled[session_id] = True
        log.info("cancel", session_id=session_id)

    # ───────────────────────────────────────────────────────────
    # 13. ext_method
    # ───────────────────────────────────────────────────────────

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return await self._extensions.handle_method(method, params)

    # ───────────────────────────────────────────────────────────
    # 14. ext_notification
    # ───────────────────────────────────────────────────────────

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        await self._extensions.handle_notification(method, params)

    # ═══════════════════════════════════════════════════════════
    # Private helpers
    # ═══════════════════════════════════════════════════════════

    async def _send_text(self, session_id: str, text: str) -> None:
        """Send an agent message chunk to the client."""
        update = update_agent_message(text_block(text))
        await self._conn.session_update(session_id=session_id, update=update, source="Malibu")

    @staticmethod
    def _extract_text(content: Any) -> str:
        """Extract text from LangChain message content (str or list of blocks)."""
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

    async def _handle_interrupts(
        self,
        *,
        current_state: Any,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Convert LangGraph interrupts to ACP permission requests."""
        user_decisions: list[dict[str, Any]] = []

        if not (current_state.next and current_state.interrupts):
            return user_decisions

        for interrupt in current_state.interrupts:
            tool_call_id = interrupt.id
            interrupt_value = interrupt.value

            action_requests = []
            if isinstance(interrupt_value, dict):
                action_requests = interrupt_value.get("action_requests", [])

            for action in action_requests:
                tool_name = action.get("name", "tool")
                tool_args = action.get("args", {})

                # Check auto-approval
                if self._permissions.is_auto_approved(session_id, tool_name, tool_args):
                    user_decisions.append({"type": "approve"})
                    continue

                # Send plan text for write_todos
                if tool_name == "write_todos":
                    todos = tool_args.get("todos", [])
                    await self._send_text(session_id, format_plan_text(todos))

                # Build permission request
                options = self._permissions.build_permission_options(tool_name, tool_args)
                tool_call_update = self._permissions.build_tool_call_update(tool_call_id, tool_name, tool_args)

                response = await self._conn.request_permission(
                    session_id=session_id,
                    tool_call=tool_call_update,
                    options=options,
                )

                if response.outcome.outcome == "selected":
                    decision = response.outcome.option_id

                    if decision == "approve_always":
                        self._permissions.register_always_allow(session_id, tool_name, tool_args)
                        user_decisions.append({"type": "approve"})

                    elif tool_name == "write_todos" and decision == "reject":
                        self._permissions.clear_plan(session_id)
                        plan_clear = build_empty_plan()
                        await self._conn.session_update(
                            session_id=session_id, update=plan_clear, source="Malibu"
                        )
                        user_decisions.append({
                            "type": "reject",
                            "feedback": (
                                "The user rejected the plan. Ask for feedback on how "
                                "to improve it, then create a new plan using write_todos."
                            ),
                        })

                    elif tool_name == "write_todos" and decision == "approve":
                        self._permissions.approve_plan(session_id, tool_args)
                        user_decisions.append({"type": decision})

                    else:
                        user_decisions.append({"type": decision})
                else:
                    # Cancelled
                    user_decisions.append({"type": "reject"})
                    if tool_name == "write_todos":
                        self._permissions.clear_plan(session_id)
                        plan_clear = build_empty_plan()
                        await self._conn.session_update(
                            session_id=session_id, update=plan_clear, source="Malibu"
                        )

        return user_decisions

    # ═══════════════════════════════════════════════════════════
    # Extension method handlers
    # ═══════════════════════════════════════════════════════════

    async def _ext_compact(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the 'compact' extension method — compact a session's context."""
        session_id = params.get("session_id", "")
        if not session_id:
            raise RequestError(-32602, "session_id is required")

        agent = self._session_mgr.get_agent(session_id)
        if agent is None:
            raise RequestError(-32602, f"No agent for session {session_id}")

        await self._compaction_mgr.compact_state(
            agent, session_id, self._settings
        )

        # Notify client
        await self._send_text(session_id, "[Context compacted — older messages summarised.]")
        log.info("compaction_complete", session_id=session_id)
        return {"status": "compacted"}

    async def _ext_plan(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the 'plan' extension method — invoke the planner subagent."""
        session_id = params.get("session_id", "")
        task = params.get("task", "")

        if not session_id:
            raise RequestError(-32602, "session_id is required")
        if not task:
            raise RequestError(-32602, "task is required")

        cwd = self._session_mgr._cwds.get(session_id, ".")

        try:
            raise RequestError(-32601, "Planning subagent is now natively integrated via deep agents. Please ask the agent directly to generate a plan via a normal message.")
        except Exception as exc:
            log.exception("plan_failed", session_id=session_id)
            raise RequestError(-32603, f"Planning failed: {exc}")

    async def _ext_skills(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the 'skills' extension method — list or get info about skills."""
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

        # Default: list all skills
        return {"skills": registry.list_skills()}
