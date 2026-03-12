# Malibu - Public API Mapping

This document maps every source module to its public API (classes, functions, constants) that should have test coverage.

---

## malibu/__init__.py
```
VERSION = "0.1.0"
```

## malibu/config.py
**Classes:**
- `Settings` - Pydantic BaseSettings with database, LLM, auth, server, security, API, telemetry configs
  - `resolve_allowed_paths(cwd: str) -> list[Path]`
  - `create_llm() -> BaseChatModel` - Factory for OpenAI/Anthropic models

## malibu/agent/__init__.py
**Re-exports (public API):**
- `build_agent` - from graph.py
- `build_middleware_stack` - from middleware.py
- `build_system_prompt` - from prompts.py
- `load_local_context` - from middleware.py
- `get_interrupt_on` - from modes.py
- `DEFAULT_MODES` - from modes.py
- `SessionMeta` - from state.py
- `ALL_TOOLS` - from tools.py

## malibu/agent/graph.py
**Functions:**
- `build_agent(settings: Settings, cwd: str, mode: str, checkpointer: Any | None) -> CompiledStateGraph`

## malibu/agent/middleware.py
**Functions:**
- `build_hitl_middleware(mode_id: str) -> HumanInTheLoopMiddleware | None`
- `load_local_context(cwd: str) -> str | None`
- `build_middleware_stack(mode_id: str) -> list[...]`
- `log_tool_calls(tool_call: Any, config: Any) -> Any` (async, @wrap_tool_call)

## malibu/agent/modes.py
**Constants:**
- `DEFAULT_MODES: SessionModeState` - 3 modes: ask_before_edits, accept_edits, accept_everything
- `INTERRUPT_ON_BY_MODE: dict[str, dict[str, dict | bool]]`

**Functions:**
- `get_interrupt_on(mode_id: str) -> dict[str, dict | bool]`

## malibu/agent/prompts.py
**Functions:**
- `build_system_prompt(cwd: str, mode: str, extra_context: str | None = None) -> str`

## malibu/agent/state.py
**Classes:**
- `SessionMeta` - dataclass
  - `session_id: str`
  - `cwd: str`
  - `mode: str = "accept_edits"`
  - `model: str = "openai:gpt-4o"`
  - `todos: list[dict[str, Any]]` (default_factory=list)

## malibu/agent/tools.py
**@tool Functions (LangChain tools):**
- `read_file(file_path: str, line: int | None = None, limit: int | None = None) -> str`
- `write_file(file_path: str, content: str) -> str`
- `edit_file(file_path: str, old_string: str, new_string: str) -> str`
- `ls(path: str = ".", glob_pattern: str | None = None) -> str`
- `grep(pattern: str, path: str = ".") -> str`
- `write_todos(todos: list[dict[str, str]]) -> str`
- `execute(command: str, shell: bool = False) -> str`

**Constants:**
- `ALL_TOOLS: list[...]` - All tool functions bundled for create_agent()

## malibu/api/app.py
**Functions:**
- `create_app() -> FastAPI` - FastAPI application factory

## malibu/api/routes.py
**Models:**
- `SessionCreateRequest`, `SessionCreateResponse`
- `PromptRequest`, `PromptResponse`
- `ModeChangeRequest`, `ConfigOptionRequest`

**Endpoints (all 501 Not Implemented stubs):**
- GET `/health` -> dict
- POST `/sessions` - create_session
- POST `/prompt` - prompt
- POST `/sessions/mode` - set_mode
- POST `/sessions/config` - set_config
- GET `/sessions` - list_sessions

## malibu/api/websocket.py
**Endpoints:**
- WebSocket `/session/{session_id}` - session_ws

## malibu/auth/jwt_handler.py
**Classes:**
- `JWTHandler`
  - `create_token(user_id: str, extra_claims: dict[str, Any] | None = None) -> str`
  - `verify_token(token: str) -> dict[str, Any]`
  - `refresh_token(token: str) -> str`

## malibu/auth/middleware.py
**Constants:**
- `HEADER_KEY = "authorization"`

**Classes:**
- `AuthMiddleware`
  - `verify(metadata: dict[str, Any] | None) -> str | None`
  - `require(metadata: dict[str, Any] | None) -> str`

## malibu/auth/providers.py
**Classes:**
- `AuthProvider` (ABC)
  - `authenticate(credential: str) -> str | None`
- `JWTProvider(AuthProvider)`
  - `authenticate(credential: str) -> str | None`
  - `issue(user_id: str) -> str`
- `APIKeyProvider(AuthProvider)`
  - `authenticate(credential: str) -> str | None`
  - `generate_key() -> tuple[str, str]` (static)
  - `hash_key(plain_key: str) -> str` (static)
- `CompositeAuthProvider(AuthProvider)`
  - `authenticate(credential: str) -> str | None`

## malibu/client/accumulator.py
**Classes:**
- `MalibuSessionAccumulator`
  - `get_or_create(session_id: str) -> SessionAccumulator`
  - `process_update(session_id: str, update: Any) -> None`
  - `snapshot(session_id: str) -> SessionSnapshot | None`
  - `clear(session_id: str) -> None`

## malibu/client/client.py
**Classes:**
- `MalibuClient(Client)` - Implements 11 ACP client methods:
  - `on_connect(conn: Agent) -> None`
  - `request_permission(tool_call: ToolCallUpdate, options: list[PermissionOption]) -> RequestPermissionResponse`
  - `session_update(session_id: str, update: Any) -> None`
  - `write_text_file(path: str, content: str) -> WriteTextFileResponse`
  - `read_text_file(path: str, line: int | None = None, limit: int | None = None) -> ReadTextFileResponse`
  - `create_terminal(command: str, args: list[str] | None = None, env: list[EnvVariable] | None = None) -> CreateTerminalResponse`
  - `terminal_output(terminal_id: str) -> TerminalOutputResponse`
  - `release_terminal(terminal_id: str) -> ReleaseTerminalResponse`
  - `wait_for_terminal_exit(terminal_id: str) -> WaitForTerminalExitResponse`
  - `kill_terminal(terminal_id: str) -> KillTerminalCommandResponse`
  - `ext_method(method: str, params: dict[str, Any]) -> dict[str, Any]`
  - `ext_notification(method: str, params: dict[str, Any]) -> None`

## malibu/client/file_ops.py
**Classes:**
- `FileOperations`
  - `read_text_file(path: str, line: int | None = None, limit: int | None = None) -> ReadTextFileResponse` (async)
  - `write_text_file(path: str, content: str) -> WriteTextFileResponse | None` (async)

## malibu/client/permissions_ui.py
**Functions:**
- `interactive_permission_prompt(options: list[PermissionOption], tool_call: ToolCallUpdate) -> RequestPermissionResponse` (async)

## malibu/client/session_display.py
**Functions:**
- `display_session_update(session_id: str, update: Any, **kwargs: Any) -> None`

## malibu/client/terminal_mgr.py
**Classes:**
- `TerminalExitResult` - dataclass (exit_code: int, output: str)
- `TerminalManager`
  - `create_terminal(command: str, args: list[str] | None = None, env: list[EnvVariable] | None = None) -> CreateTerminalResponse` (async)
  - `terminal_output(terminal_id: str) -> TerminalOutputResponse` (async)
  - `release_terminal(terminal_id: str) -> ReleaseTerminalResponse` (async)
  - `wait_for_terminal_exit(terminal_id: str) -> WaitForTerminalExitResponse` (async)
  - `kill_terminal(terminal_id: str) -> KillTerminalCommandResponse` (async)

## malibu/persistence/connection.py
**Functions:**
- `init_db(settings: Settings) -> None` (async)
- `close_db() -> None` (async)
- `get_session_factory() -> async_sessionmaker[AsyncSession]`
- `get_engine() -> AsyncEngine`

## malibu/persistence/models.py
**Classes:**
- `SessionRecord` - SQLAlchemy model
- `MessageRecord` - SQLAlchemy model
- `ToolCallRecord` - SQLAlchemy model
- `PlanRecord` - SQLAlchemy model
- `CommandAllowlistRecord` - SQLAlchemy model
- `ApiKeyRecord` - SQLAlchemy model

## malibu/persistence/repository.py
**Classes:**
- `SessionRepository`
  - `create(cwd: str, mode_id: str | None = None, model_id: str | None = None) -> SessionRecord` (async)
  - `get_by_session_id(session_id: str) -> SessionRecord | None` (async)
  - `list_sessions(cwd: str | None = None, cursor: str | None = None, limit: int = 50) -> Sequence[SessionRecord]` (async)
  - `update_mode(session_id: str, mode_id: str) -> None` (async)
  - `update_model(session_id: str, model_id: str) -> None` (async)
  - `update_title(session_id: str, title: str) -> None` (async)
  - `update_config(session_id: str, config_json: dict) -> None` (async)
  - `deactivate(session_id: str) -> None` (async)
  - `fork(source_session_id: str, cwd: str) -> SessionRecord` (async)
- `MessageRepository` (similar CRUD ops)
- `ToolCallRepository` (similar CRUD ops)
- `PlanRepository` (similar CRUD ops)
- `CommandAllowlistRepository` (similar CRUD ops)

## malibu/server/agent.py
**Classes:**
- `MalibuAgent(ACPAgent)` - Implements 15 ACP agent methods:
  - `initialize(client_capabilities: ClientCapabilities, ...) -> InitializeResponse` (async)
  - `new_session(cwd: str, ...) -> NewSessionResponse` (async)
  - `load_session(session_id: str) -> LoadSessionResponse` (async)
  - `list_sessions(...) -> ListSessionsResponse` (async)
  - `prompt(session_id: str, messages: list[...]) -> PromptResponse` (async, generator)
  - `request_interrupt(session_id: str, ...) -> None` (async)
  - `cancel(session_id: str) -> None` (async)
  - `set_session_mode(session_id: str, mode_id: str) -> SetSessionModeResponse` (async)
  - `set_session_model(session_id: str, model_id: str) -> SetSessionModelResponse` (async)
  - `set_session_config_option(session_id: str, option_id: str, value: str) -> SetSessionConfigOptionResponse` (async)
  - `fork_session(source_session_id: str, cwd: str) -> ForkSessionResponse` (async)
  - `resume_session(session_id: str, messages: list[...]) -> ResumeSessionResponse` (async, generator)
  - `authenticate(method_id: str, ...) -> AuthenticateResponse | None` (async)
  - `ext_method(method: str, params: dict[str, Any]) -> dict[str, Any]` (async)
  - `ext_notification(method: str, params: dict[str, Any]) -> None` (async)

## malibu/server/auth.py
**Classes:**
- `ServerAuthHandler`
  - `authenticate(method_id: str, **kwargs: Any) -> AuthenticateResponse | None` (async)

## malibu/server/config_options.py
**Classes:**
- `ConfigUpdateResult` - dataclass (config_id: str, value: Any)
- `ConfigOptionManager`
  - `get_config(session_id: str) -> dict[str, Any]`
  - `set_option(session_id: str, config_id: str, value: str) -> ConfigUpdateResult | None`
  - `clear_session(session_id: str) -> None`

## malibu/server/content.py
**Functions:**
- `convert_text_block(block: TextContentBlock) -> list[dict[str, str]]`
- `convert_image_block(block: ImageContentBlock) -> list[dict[str, object]]`
- `convert_audio_block(block: AudioContentBlock) -> list[dict[str, str]]`
- `convert_resource_block(block: ResourceContentBlock, root_dir: str) -> list[dict[str, str]]`
- `convert_embedded_resource_block(block: EmbeddedResourceContentBlock) -> list[dict[str, str]]`
- `convert_any_block(block, root_dir: str = "") -> list[dict[str, str]]`

## malibu/server/extensions.py
**Classes:**
- `ExtensionRegistry`
  - `register_method(method: str, handler: Any) -> None`
  - `register_notification(method: str, handler: Any) -> None`
  - `handle_method(method: str, params: dict[str, Any]) -> dict[str, Any]` (async)
  - `handle_notification(method: str, params: dict[str, Any]) -> None` (async)

## malibu/server/permissions.py
**Classes:**
- `PermissionManager`
  - `is_auto_approved(session_id: str, tool_name: str, tool_args: dict[str, Any]) -> bool`
  - `register_always_allow(session_id: str, tool_name: str, tool_args: dict[str, Any]) -> None`
  - `approve_plan(session_id: str, tool_args: dict[str, Any]) -> None`
  - `clear_plan(session_id: str) -> None`
  - `build_permission_options(tool_name: str, tool_args: dict[str, Any]) -> list[PermissionOption]`

## malibu/server/plans.py
**Functions:**
- `build_plan_update(todos: list[dict[str, Any]]) -> AgentPlanUpdate`
- `build_empty_plan() -> AgentPlanUpdate`
- `all_tasks_completed(todos: list[dict[str, Any]]) -> bool`
- `format_plan_text(todos: list[dict[str, Any]]) -> str`

## malibu/server/security.py
**Functions:**
- `extract_command_types(command: str) -> list[str]`
- `truncate_command_for_display(command: str, max_length: int = 80) -> str`

## malibu/server/sessions.py
**Classes:**
- `SessionManager`
  - `create_session(session_id: str, cwd: str, mode_id: str | None = None) -> CompiledStateGraph`
  - `get_agent(session_id: str) -> CompiledStateGraph | None`
  - `get_or_create_agent(session_id: str, cwd: str) -> CompiledStateGraph`
  - `set_mode(session_id: str, mode_id: str) -> None`
  - `set_model(session_id: str, model_id: str) -> None`

## malibu/server/streaming.py
**Classes:**
- `ToolCallAccumulator`
  - `process_chunk(message_chunk: Any) -> list[ToolCallStart]`

**Functions:**
- `create_tool_call_start(...) -> ToolCallStart`
- `format_execute_result(...) -> str`

## malibu/telemetry/logging.py
**Functions:**
- `setup_logging(settings: Settings) -> None`
- `get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger`

## malibu/telemetry/tracing.py
**Functions:**
- `init_tracing(settings: Settings) -> None`
- `span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]` (context manager)
- `async_span(name: str, attributes: dict[str, Any] | None = None) -> AsyncIterator[Any]` (async context manager)
- `get_tracer() -> Any`
