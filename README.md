<div align="center">
  <h1>Malibu</h1>
  <p><strong>AI-powered terminal coding agent with rich TUI, built on LangGraph, LangChain, and ACP.</strong></p>
  <p>
    <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-0f766e"></a>
    <img alt="Python" src="https://img.shields.io/badge/python-3.11+-1d4ed8">
    <img alt="Architecture" src="https://img.shields.io/badge/agent-Terminal%20Coding%20Agent-0f172a">
  </p>
</div>

Malibu is a terminal-based coding agent for real project work — code edits, planning, Git operations, skills, hooks, plugins, guarded tool execution, and session continuity — all in a rich, branded terminal interface.

## Quick Start

```bash
# 1) Clone and install
git clone https://github.com/obinopaul/malibu.git
cd malibu
uv sync

# 2) Configure environment
cp .env.example .env
# Edit .env — set at least LLM_API_KEY (or OPENAI_API_KEY)

# 3) Launch
malibu
```

That's it. Type `malibu` and the terminal UI launches immediately — welcome screen, branded interface, and chat input ready to go.

## Usage

### Interactive Terminal UI (Default)

```bash
malibu                              # Launch the TUI
malibu "fix the login bug"          # Launch with an initial prompt
malibu --continue                   # Resume the most recent session
malibu --resume                     # Pick a session to resume interactively
malibu --resume <session-id>        # Resume a specific session
malibu --no-welcome                 # Skip the splash screen
```

### Non-Interactive Mode

```bash
malibu --prompt "refactor auth.py"  # Execute a single prompt and exit
```

### Server / Client (ACP Protocol)

```bash
malibu server                       # Run as ACP agent on stdio
malibu client <cmd>                 # Connect to an agent process
malibu duet                         # Legacy: agent + client in one process
```

### Other Commands

```bash
malibu --version                    # Print version
malibu --help                       # Show all options
malibu generate-key                 # Generate a new API key
```

## Terminal UI Features

The TUI is built with [Textual](https://textual.textualize.io/) and includes:

- **Welcome Screen** — ASCII art banner, version info, quick-start hints
- **Chat Screen** — StatusBar (mode, tokens, session), scrollable MessageList, ChatInput
- **Plan Panel** — Toggle with `Ctrl+P` to view agent plans
- **Approval Modals** — Human-in-the-loop permission prompts for dangerous operations
- **Tool Call Rendering** — Visual indicators for file reads, edits, searches, and shell execution
- **Slash Commands** — `/help`, `/mode`, `/model`, `/clear`, `/compact`, `/config`, `/mcp`, `/plan`, `/session`, `/skills`
- **Ocean-Blue Theme** — Branded color palette with dark mode

## Architecture

| Subsystem | Purpose |
|-----------|---------|
| **Runtime** | Command safety checks, cost tracking, hierarchical config |
| **Git** | Git operations, worktree management, branch protection |
| **Hooks** | Lifecycle triggers (session, tool, compaction events) |
| **Plugins** | Installable skill bundles with marketplace support |
| **Skills** | SKILL.md-based reusable capabilities with multi-scope precedence |
| **Agent** | LangGraph orchestration, middleware stack, prompt composition |
| **TUI** | Textual-based terminal interface with widgets and screens |
| **Server** | ACP protocol server with streaming and session management |

### Skills System

Skills are directory packages with `SKILL.md` and optional support folders. Load precedence (later overrides earlier):

1. `malibu/skills/builtin/`
2. `~/.malibu/skills/`
3. `~/.agents/skills/`
4. `.malibu/skills/`
5. `.agents/skills/`
6. Enabled plugin skills

### Hooks

Lifecycle triggers for automation and policy enforcement:

- `SESSION_START` / `SESSION_END` — session lifecycle
- `PRE_TOOL_CALL` / `POST_TOOL_CALL` — tool execution wrapping
- `PRE_COMPACT` — before context compaction
- `USER_PROMPT_SUBMIT` — before user prompts reach the agent

### Plugins

Installable capability bundles:

```bash
/skills                              # List all loaded skills
```

Plugins can provide skills, hooks, and configuration. Install from local directories or marketplaces.

## Development

```bash
uv run python -m pytest tests/ -v    # Run tests
uv run ruff check .                  # Lint
uv run ruff format .                 # Format
```

## ACP Documentation

Legacy ACP-first documentation is preserved in [ACP_README.md](./ACP_README.md).

## License

MIT
