# Malibu Project - Complete Exploration

## Source Module Files (malibu/malibu/) - Full Paths

### Root & Entry
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\__init__.py` - Main package init (version=0.1.0)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\__main__.py` - CLI dispatcher (server, client, duet, generate-key commands)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\config.py` - Settings/configuration via Pydantic BaseSettings

### Agent Logic (malibu/agent/)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\agent\__init__.py` - Public API (re-exports build_agent, build_middleware_stack, etc.)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\agent\graph.py` - build_agent() factory using langchain.agents.create_agent()
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\agent\middleware.py` - HumanInTheLoopMiddleware, tool call logging, local context injection
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\agent\modes.py` - SessionModes & interrupt_on configs
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\agent\prompts.py` - build_system_prompt() with mode-aware instructions
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\agent\state.py` - SessionMeta dataclass
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\agent\tools.py` - @tool decorators (read_file, write_file, edit_file, ls, grep, write_todos, execute)

### Auth Layer (malibu/auth/)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\auth\__init__.py` - Empty
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\auth\jwt_handler.py` - JWTHandler (create_token, verify_token, refresh_token)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\auth\middleware.py` - AuthMiddleware (verify, require)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\auth\providers.py` - JWTProvider, APIKeyProvider, CompositeAuthProvider

### Client Layer (malibu/client/)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\client\__init__.py` - Empty
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\client\client.py` - MalibuClient (impl all 11 client methods + on_connect)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\client\accumulator.py` - MalibuSessionAccumulator (session state tracking)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\client\file_ops.py` - FileOperations (read_text_file, write_text_file with path validation)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\client\permissions_ui.py` - interactive_permission_prompt()
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\client\session_display.py` - display_session_update() for all 11 update types
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\client\terminal_mgr.py` - TerminalManager (all 5 terminal methods)

### Persistence Layer (malibu/persistence/)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\persistence\__init__.py` - Empty
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\persistence\connection.py` - init_db(), close_db(), get_session_factory(), get_engine()
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\persistence\models.py` - SQLAlchemy ORM models (SessionRecord, MessageRecord, ToolCallRecord, PlanRecord, CommandAllowlistRecord, ApiKeyRecord)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\persistence\repository.py` - SessionRepository, MessageRepository, ToolCallRepository, PlanRepository, CommandAllowlistRepository

### Server Layer (malibu/server/)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\server\__init__.py` - Empty
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\server\agent.py` - MalibuAgent (impl all 15 agent methods)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\server\auth.py` - ServerAuthHandler (authenticate() for jwt/api_key)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\server\config_options.py` - ConfigOptionManager (temperature, max_tokens, etc.)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\server\content.py` - convert_*_block() functions for all ACP content types
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\server\extensions.py` - ExtensionRegistry (ext_method, ext_notification dispatchers)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\server\permissions.py` - PermissionManager (approval workflows, allowlists)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\server\plans.py` - build_plan_update(), format_plan_text(), all_tasks_completed()
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\server\security.py` - extract_command_types(), truncate_command_for_display()
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\server\sessions.py` - SessionManager (session lifecycle, mode/model switching)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\server\streaming.py` - ToolCallAccumulator, create_tool_call_start(), format_execute_result()

### Telemetry Layer (malibu/telemetry/)
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\telemetry\__init__.py` - Empty
- `c:\Users\pault\Downloads\python-sdk\malibu\malibu\telemetry\logging.py` - setup_logging(), get_logger() via structlog

## Test Files (malibu/tests/) - Full Paths

- `c:\Users\pault\Downloads\python-sdk\malibu\tests\__init__.py` - Empty
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\conftest.py` - Shared test fixtures (settings, mocks, db)
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_accumulator.py` - MalibuSessionAccumulator tests
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_auth.py` - JWTHandler, JWTProvider, APIKeyProvider, CompositeAuthProvider tests
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_config.py` - Settings tests
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_config_options.py` - ConfigOptionManager tests
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_content.py` - convert_*_block() functions tests
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_extensions.py` - ExtensionRegistry tests
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_file_ops.py` - FileOperations tests
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_permissions.py` - PermissionManager tests
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_plans.py` - Plan builder functions tests
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_security.py` - extract_command_types(), truncate_command tests
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_session_display.py` - display_session_update() tests
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_streaming.py` - ToolCallAccumulator, streaming helpers tests
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_telemetry.py` - logging setup and utilities tests
- `c:\Users\pault\Downloads\python-sdk\malibu\tests\test_terminal_mgr.py` - TerminalManager tests

## Coverage Summary

**Total Source Modules**: 30 (plus __init__.py files)
**Total Test Files**: 17

### Coverage Status
- ✅ Full test coverage: agent/, auth/, client/, server/ (permissions, plans, security, streaming, content, extensions, config_options), telemetry/
- ⚠️ Partial coverage: persistence/ (module exists but tests missing)
- ❌ NO test coverage: config.py (Settings), __main__.py (CLI commands), agent/graph.py (create_agent factory), agent/middleware.py, agent/tools.py, client/client.py (MalibuClient impl), server/agent.py (MalibuAgent impl), server/sessions.py (SessionManager), persistence/connection.py, persistence/repository.py

### GAP ANALYSIS

**CRITICAL GAPS**:
1. **MalibuAgent** - No tests for the entire 15-method Agent implementation
2. **MalibuClient** - No tests for the 11 Client methods
3. **SessionManager** - No tests for session lifecycle, mode switching, model switching
4. **Persistence** - No tests for database models or repositories (critical for state management)
5. **build_agent()** - No tests for the LangGraph agent factory
6. **Agent tools** - No tests for tool implementations (read_file, write_file, execute, etc.)
7. **__main__.py** - No CLI command tests

**RECOMMENDATION**: Priority for testing:
1. malibu/server/agent.py - MalibuAgent (15 methods)
2. malibu/persistence/ - Connection, Models, Repositories
3. malibu/server/sessions.py - SessionManager
4. malibu/agent/graph.py - build_agent factory
5. malibu/client/client.py - MalibuClient methods
6. malibu/agent/tools.py - Tool implementations
