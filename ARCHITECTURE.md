# Malibu Architecture

## Overview

Malibu is a production-grade ACP (Agent-Client Protocol) agent harness that implements the complete ACP specification. It consists of three primary layers:

```
┌──────────────────────────────────────────────────┐
│                   CLI / API                       │
│  __main__.py  │  api/app.py  │  api/routes.py    │
├──────────────────────────────────────────────────┤
│              ACP Protocol Layer                   │
│  ┌──────────────────┐  ┌──────────────────────┐  │
│  │   MalibuAgent     │  │   MalibuClient       │  │
│  │  (15 methods)     │  │  (11 methods)        │  │
│  │  server/agent.py  │  │  client/client.py    │  │
│  └──────────────────┘  └──────────────────────┘  │
├──────────────────────────────────────────────────┤
│              Agent Core (LangGraph)               │
│  graph.py │ state.py │ tools.py │ modes.py       │
├──────────────────────────────────────────────────┤
│              Infrastructure                       │
│  persistence/  │  auth/  │  telemetry/            │
│  (PostgreSQL)  │ (JWT)   │ (structlog + OTel)     │
└──────────────────────────────────────────────────┘
```

## Data Flow

### Prompt Flow (Agent Side)

1. Client sends `prompt()` with content blocks
2. `MalibuAgent.prompt()` receives, converts content, builds LangGraph messages
3. LangGraph graph executes: `agent_node` → `tools` → `agent_node` (loop)
4. On tool call interrupts, permission flow is triggered via `_handle_interrupts()`
5. Streaming updates sent via `session_update()` throughout
6. Final response with `stop_reason` returned

### Permission Flow

1. Agent encounters tool call needing approval
2. `PermissionManager.build_permission_options()` generates options
3. `client.request_permission()` called with options + tool call context
4. Client renders interactive prompt (or auto-approves)
5. Response fed back to LangGraph as interrupt response

### Session Lifecycle

1. `new_session()` → creates DB record, builds LangGraph agent
2. `prompt()` → runs agent, persists messages and tool calls
3. `fork_session()` → clones session with message history
4. `set_session_mode()` → rebuilds agent with new interrupt config
5. Session cleanup on disconnect

## Module Responsibilities

### `server/` — ACP Agent Protocol

| Module | Purpose |
|---|---|
| `agent.py` | Main Agent class — all 15 protocol methods |
| `content.py` | Convert between ACP content blocks and LangChain messages |
| `security.py` | Classify commands for permission decisions |
| `streaming.py` | Accumulate tool call chunks into structured updates |
| `plans.py` | Build and manage plan updates |
| `permissions.py` | Permission management and auto-approval logic |
| `auth.py` | Server-side authentication handler |
| `sessions.py` | Session lifecycle (create, fork, mode switch) |
| `config_options.py` | Runtime config option schema and validation |
| `extensions.py` | Custom extension method/notification dispatch |

### `client/` — ACP Client Protocol

| Module | Purpose |
|---|---|
| `client.py` | Main Client class — all 11 protocol methods |
| `file_ops.py` | Secure file read/write with path allowlisting |
| `terminal_mgr.py` | Async subprocess terminal management |
| `permissions_ui.py` | Interactive permission prompt rendering |
| `session_display.py` | Console rendering for all 11 update types |
| `accumulator.py` | Session state tracking via SDK's SessionAccumulator |

### `agent/` — LangGraph Core

| Module | Purpose |
|---|---|
| `graph.py` | `create_agent()` factory → CompiledStateGraph |
| `state.py` | `MalibuState` extending LangGraph's MessagesState |
| `tools.py` | 7 tools: read, write, edit, ls, grep, execute, todos |
| `prompts.py` | Mode-aware system prompt generation |
| `modes.py` | 3 modes (code, architect, ask) + interrupt configs |
| `middleware.py` | Local context injection + conversation trimming |

### `persistence/` — Data Layer

| Module | Purpose |
|---|---|
| `models.py` | 6 SQLAlchemy ORM models |
| `repository.py` | 5 async repository classes |
| `connection.py` | Engine + session factory management |
| `migrations/` | Alembic async migration framework |

### `auth/` — Authentication

| Module | Purpose |
|---|---|
| `jwt_handler.py` | JWT token create / verify / refresh |
| `providers.py` | JWT + API key + composite auth providers |
| `middleware.py` | Request auth middleware |

### `telemetry/` — Observability

| Module | Purpose |
|---|---|
| `logging.py` | structlog with JSON (prod) / console (dev) |
| `tracing.py` | Optional OpenTelemetry with sync/async spans |
