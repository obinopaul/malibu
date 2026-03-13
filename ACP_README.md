# Malibu — Production ACP Agent Harness

A complete, production-grade implementation of the [Agent-Client Protocol (ACP)](https://agentclientprotocol.github.io/) Python SDK. Malibu integrates every ACP feature with a LangGraph-powered agent core, PostgreSQL persistence, JWT authentication, and full observability.

## Features

- **All 15 ACP Agent protocol methods** — `initialize`, `new_session`, `load_session`, `list_sessions`, `set_session_mode`, `set_session_model`, `set_config_option`, `authenticate`, `prompt`, `fork_session`, `resume_session`, `cancel`, `ext_method`, `ext_notification`
- **All 11 ACP Client protocol methods** — `request_permission`, `session_update`, `write_text_file`, `read_text_file`, `create_terminal`, `terminal_output`, `release_terminal`, `wait_for_terminal_exit`, `kill_terminal`, `ext_method`, `ext_notification`
- **LangGraph agent core** — Multi-mode (code, architect, ask), interrupt-based HITL, tool call streaming
- **PostgreSQL persistence** — Sessions, messages, tool calls, plans, auth tokens, command allowlists
- **JWT + API key authentication** — Composite auth with bcrypt-hashed keys
- **Full observability** — structlog (JSON prod / console dev)
- **CLI entry point** — `malibu server | client | duet | generate-key`

## Quick Start

```bash
# Install
cd malibu && make install

# Copy and edit environment
cp .env.example .env

# Run in duet mode (agent + client in one process)
make run-duet
# or
uv run python -m malibu duet

# Or run server and client separately
make run-server   # in terminal 1
# or
uv run python -m malibu server

make run-client   # in terminal 2
# or
uv run python -m malibu client "your prompt here"


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
│   │   └── logging.py       #   structlog setup
│   ├── skills/              # SKILL.md-based skill system
│   │   ├── base.py          #   SkillMetadata TypedDict, YAML frontmatter parser
│   │   ├── loader.py        #   Multi-level skill discovery (builtin→user→project)
│   │   ├── registry.py      #   Skill aggregation + prompt generation
│   │   └── builtin/         #   Built-in skills (skill-creator, etc.)
│   ├── hooks/               # Lifecycle event hooks
│   │   ├── models.py        #   HookEvent enum, Hook model
│   │   └── manager.py       #   HookManager (load, execute hooks)
│   ├── plugins/             # Plugin marketplace system
│   │   ├── models.py        #   Plugin, PluginRegistry models
│   │   └── manager.py       #   PluginManager (install, enable, disable)
│   ├── snapshot/            # Git-based snapshot system
│   │   └── manager.py       #   SnapshotManager (take, diff, revert)
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

## Docker

```bash
# Start PostgreSQL + Malibu
docker compose up -d

# Run migrations
docker compose exec malibu alembic upgrade head
```

## Skills

Skills are directory-based instruction packages that augment the agent's capabilities. Each skill is a folder containing a `SKILL.md` file with YAML frontmatter and markdown instructions.

### Skill Structure

```
my-skill/
├── SKILL.md          # Required: YAML frontmatter + markdown body
├── scripts/          # Optional: helper scripts
├── references/       # Optional: reference files
└── assets/           # Optional: images, data files
```

### SKILL.md Format

```yaml
---
name: my-skill
description: >
  When to invoke this skill — the agent uses this to decide
  whether to apply the skill to the current task.
---

# My Skill

Instructions that the agent follows when this skill is active.
```

### Skill Precedence

Skills are loaded from multiple locations with later sources overriding earlier ones:

1. **Built-in** — `malibu/skills/builtin/`
2. **User (malibu)** — `~/.malibu/skills/`
3. **User (agents)** — `~/.agents/skills/`
4. **Project (malibu)** — `.malibu/skills/`
5. **Project (agents)** — `.agents/skills/`

### Using Skills

```bash
# List available skills
malibu skills list

# Get skill details
malibu skills info skill-creator
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
