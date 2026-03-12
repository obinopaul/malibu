# Malibu — Production ACP Agent Harness

A complete, production-grade implementation of the [Agent-Client Protocol (ACP)](https://agentclientprotocol.github.io/) Python SDK. Malibu integrates every ACP feature with a LangGraph-powered agent core, PostgreSQL persistence, JWT authentication, and full observability.

## Features

- **All 15 ACP Agent protocol methods** — `initialize`, `new_session`, `load_session`, `list_sessions`, `set_session_mode`, `set_session_model`, `set_config_option`, `authenticate`, `prompt`, `fork_session`, `resume_session`, `cancel`, `ext_method`, `ext_notification`
- **All 11 ACP Client protocol methods** — `request_permission`, `session_update`, `write_text_file`, `read_text_file`, `create_terminal`, `terminal_output`, `release_terminal`, `wait_for_terminal_exit`, `kill_terminal`, `ext_method`, `ext_notification`
- **LangGraph agent core** — Multi-mode (code, architect, ask), interrupt-based HITL, tool call streaming
- **PostgreSQL persistence** — Sessions, messages, tool calls, plans, auth tokens, command allowlists
- **JWT + API key authentication** — Composite auth with bcrypt-hashed keys
- **Full observability** — structlog (JSON prod / console dev) + optional OpenTelemetry tracing
- **FastAPI scaffold** — REST + WebSocket endpoints for web UI integration
- **CLI entry point** — `malibu server | client | duet | api | generate-key`

## Quick Start

```bash
# Install
cd malibu && make install

# Copy and edit environment
cp .env.example .env

# Run in duet mode (agent + client in one process)
make run-duet
# or
uv run python -m malibu run-duet

# Or run server and client separately
make run-server   # in terminal 1
# or
uv run python -m malibu server

make run-client   # in terminal 2
# or
uv run python -m malibu client "your prompt here"


# API mode
uv run python -m malibu api --host 127.0.0.1 --port 8000

# Run tests
uv run python -m pytest tests/ -v

# Lint + format
uv run ruff check .
uv run ruff format .
```

## Project Structure

```
malibu/
├── malibu/
│   ├── __init__.py          # Package version
│   ├── __main__.py          # CLI entry point
│   ├── config.py            # Pydantic Settings (env-driven)
│   ├── agent/               # LangGraph agent core
│   │   ├── graph.py         #   Agent factory (create_agent)
│   │   ├── state.py         #   MalibuState definition
│   │   ├── tools.py         #   7 tools (read/write/edit/ls/grep/execute/todos)
│   │   ├── prompts.py       #   Mode-aware system prompts
│   │   ├── modes.py         #   3 modes + interrupt configs
│   │   └── middleware.py    #   Local context + conversation history
│   ├── server/              # ACP Agent (server-side)
│   │   ├── agent.py         #   MalibuAgent (all 15 methods)
│   │   ├── content.py       #   Content block converters
│   │   ├── security.py      #   Command type extraction
│   │   ├── streaming.py     #   Tool call chunk accumulation
│   │   ├── plans.py         #   Plan update builders
│   │   ├── permissions.py   #   Permission management
│   │   ├── auth.py          #   Server auth handler
│   │   ├── sessions.py      #   Session lifecycle manager
│   │   ├── config_options.py#   Config option schema + validation
│   │   └── extensions.py    #   Extension method/notification registry
│   ├── client/              # ACP Client (client-side)
│   │   ├── client.py        #   MalibuClient (all 11 methods)
│   │   ├── file_ops.py      #   Secure file I/O
│   │   ├── terminal_mgr.py  #   Subprocess terminal management
│   │   ├── permissions_ui.py#   Interactive permission prompts
│   │   ├── session_display.py#  Session update rendering
│   │   └── accumulator.py   #   Session state accumulator
│   ├── persistence/         # Database layer
│   │   ├── models.py        #   6 SQLAlchemy ORM models
│   │   ├── repository.py    #   5 repository classes
│   │   ├── connection.py    #   Async engine + session factory
│   │   └── migrations/      #   Alembic migrations
│   ├── auth/                # Authentication
│   │   ├── jwt_handler.py   #   JWT create/verify/refresh
│   │   ├── providers.py     #   JWT + API key + composite providers
│   │   └── middleware.py    #   Auth middleware
│   ├── telemetry/           # Observability
│   │   ├── logging.py       #   structlog setup
│   │   └── tracing.py       #   OpenTelemetry (optional)
│   └── api/                 # FastAPI scaffold
│       ├── app.py           #   Application factory
│       ├── routes.py        #   REST endpoints
│       └── websocket.py     #   WebSocket endpoint
├── tests/                   # Pytest test suite (15+ test files)
├── scripts/                 # Shell scripts
├── pyproject.toml           # Project metadata + deps
├── Makefile                 # Development commands
├── Dockerfile               # Multi-stage container build
├── docker-compose.yml       # PostgreSQL + Malibu
└── .env.example             # Environment template
```

## Configuration

All configuration is via environment variables (loaded from `.env`):

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Database connection URI |
| `LLM_MODEL` | `openai:gpt-4o` | Model in `provider:name` format |
| `LLM_API_KEY` | *(empty)* | API key for LLM provider (falls back to `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`) |
| `LLM_BASE_URL` | *(none)* | Custom endpoint URL |
| `JWT_SECRET` | required | Secret for JWT signing |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_EXPIRY_HOURS` | `24` | Token expiry |
| `ALLOWED_PATHS` | *(empty → cwd)* | JSON list of allowed directories |
| `MAX_FILE_SIZE` | `10485760` | Max file size in bytes (10MB) |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `API_HOST` | `0.0.0.0` | FastAPI bind host |
| `API_PORT` | `8000` | FastAPI bind port |
| `OTEL_ENABLED` | `false` | Enable OpenTelemetry tracing |

## Docker

```bash
# Start PostgreSQL + Malibu
docker compose up -d

# Run migrations
docker compose exec malibu alembic upgrade head
```

## Communication Architecture

Malibu supports multiple communication layers at different maturity levels.

### ACP over stdio (Primary — fully wired)

The default and production-ready transport. The agent and client exchange
JSON-RPC messages over **stdin/stdout** using the
[Agent-Client Protocol](https://agentclientprotocol.github.io/). Streaming is
token-by-token — the agent emits `session_update` calls for every chunk (text
tokens, tool-call starts/completions, plan updates) and the client receives
them in real time.

| File | Role |
|------|------|
| `malibu/server/streaming.py` | Stream processing, `ToolCallAccumulator` |
| `malibu/server/agent.py` | `prompt()` with LangGraph `astream()` |
| `malibu/server/connection.py` | ACP connection wrapper |

Used by: `malibu server`, `malibu client <cmd>`, `malibu duet`.

### WebSocket (scaffolded — not yet wired)

A WebSocket endpoint exists at `ws://<host>/ws/session/{session_id}`. It
accepts connections and handles `ping`/`pong`, but **prompt messages are not
yet wired** to the agent backend.

| File | Role |
|------|------|
| `malibu/api/websocket.py` | WebSocket route |
| `tests/test_websocket.py` | Connection + ping/pong tests |

**To wire up:** accept `{"type": "prompt", "message": "..."}`, create/reuse a
`MalibuAgent` session, call `agent.prompt()` with streaming, and relay each
`session_update` as a JSON frame back to the client.

### REST API (scaffolded — 501 stubs)

FastAPI routes under `/api/v1/` for session management and prompting. Only
`/health` is functional; the remaining endpoints return **501 Not Implemented**.

| File | Role |
|------|------|
| `malibu/api/routes.py` | REST endpoints |
| `malibu/api/app.py` | FastAPI application factory |
| `tests/test_api.py` | Health + stub-status tests |

Endpoints to wire: `POST /sessions`, `POST /prompt`, `GET /sessions`,
`POST /sessions/mode`, `POST /sessions/config`.

### SSE (not yet implemented)

Server-Sent Events are **not currently implemented** but would be a natural
addition for web clients that only need server→client streaming. An SSE
endpoint could be added as a `StreamingResponse` in FastAPI that yields
`session_update` events as `text/event-stream` data. This is simpler than
WebSockets and works well through proxies, CDNs, and HTTP/2.

A possible route: `GET /api/v1/sessions/{session_id}/stream` returning an
`EventSourceResponse` (via the `sse-starlette` package) with each ACP
`session_update` serialised as a named SSE event.

### Choosing a transport

| Transport | Direction | Complexity | Best for |
|-----------|-----------|------------|----------|
| ACP stdio | Bidirectional | Low (built-in) | CLI tools, subprocess embedding |
| WebSocket | Bidirectional | Medium | Chat UIs, real-time dashboards |
| SSE | Server → Client | Low | Simple web streams, mobile apps |
| REST | Request/Response | Low | One-shot queries, admin ops |

## Testing

```bash
# Unit tests (192 tests)
make test              # or: uv run python -m pytest tests/ -v
make test-cov          # with coverage report

# End-to-end runtime tests (requires LLM_API_KEY or OPENAI_API_KEY)
uv run python scripts/test_runtime.py    # mock transport, tests prompts + tool calls
uv run python scripts/test_duet.py       # real subprocess, 3 prompts over ACP stdio

# Interactive manual test
make run-duet
# Then type questions at the > prompt

# Quality checks (format + lint + type check)
make check
```

## License

MIT
