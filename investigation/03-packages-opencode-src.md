# packages/opencode/src — Module Deep Dive

This file documents every module inside `packages/opencode/src/` — the core CLI engine.

## Entry Point

`packages/opencode/src/index.ts` — CLI entry. Bootstraps the project, initializes the database, sets up logging, then hands off to the Yargs command parser.

---

## Module Inventory

### ESSENTIAL — Core Agent & Session

#### `agent/`
Multi-agent orchestration engine. Defines the built-in agents (`build`, `plan`, `general`, `explore`, etc.) and routes tasks to the appropriate agent. Contains the main agent loop that calls LLM providers, dispatches tool calls, and streams results back to the CLI.

**Status:** Essential — the heart of OpenCode.

#### `session/`
Conversation lifecycle management. Key files:
- `index.ts` (27KB) — Session CRUD, message storage, event emission
- `prompt.ts` (68KB) — Builds the full LLM prompt from message history, instructions, tool definitions, and system context
- `llm.ts` — LLM call wrapper with retry, streaming, and error handling
- `message.ts` / `message-v2.ts` — Message schema definitions (v1 and v2 formats)
- `compaction.ts` — Context window optimization: summarizes old messages to stay within token limits
- `processor.ts` — Message processing pipeline
- `instruction.ts` — Instruction formatting for the system prompt
- `system.ts` — System prompt assembly

**Status:** Essential — persistence, prompt building, context management.

#### `provider/`
LLM provider abstraction layer. Wraps the Vercel AI SDK to support 20+ providers:
- Anthropic (Claude), OpenAI (GPT-4, o1), Google (Vertex/Gemini), Azure OpenAI, Amazon Bedrock
- Mistral, Groq, DeepInfra, Cerebras, Cohere, OpenRouter, GitHub Copilot, GitLab
- XAI (Grok), TogetherAI, Gateway, Perplexity, and more

Key files:
- `provider.ts` — Provider factory, discovery, model listing
- `models.ts` — Model catalog and selection
- `transform.ts` — Provider-specific message transformations
- `auth.ts` — Provider authentication handling
- `error.ts` — Provider error normalization

**Status:** Essential — LLM abstraction.

#### `config/`
Configuration system. The `config.ts` file (56KB) defines the full schema for `opencode.jsonc` files:
- Agent definitions and overrides
- Provider and model settings
- Permission rules
- Plugin configurations
- TUI preferences
- Tool settings

Also contains `paths.ts` (platform-aware paths), `markdown.ts` (config parsing), `tui.ts` / `tui-schema.ts` (TUI-specific config).

**Status:** Essential — all configuration flows through here.

---

### ESSENTIAL — CLI & Commands

#### `cli/`
The command-line interface. Uses Yargs for argument parsing.

Top-level commands (`cli/cmd/`):
| Command | Purpose |
|---------|---------|
| `run.ts` | Main agent execution — inline output rendering mode |
| `serve.ts` | Start OpenCode as a local HTTP server |
| `acp.ts` | Agent Client Protocol (IDE integration) |
| `mcp.ts` | Model Context Protocol server management |
| `agent.ts` | Agent management commands |
| `session.ts` | Session management (list, load, delete) |
| `generate.ts` | Code generation commands |
| `debug.ts` | Debug/diagnostic commands |
| `upgrade.ts` | Self-upgrade command |
| `github.ts` | GitHub integration commands |
| `login.ts` | Authentication commands |
| `models.ts` | List available models |

TUI mode (`cli/cmd/tui/`):
Full interactive terminal UI using Ink (React for terminals). Components include:
- `app.tsx` — Main TUI application
- `attach.ts` — Attach to a running session
- Dialogs: agent, model, MCP, provider, session, skill, stash, theme, workspace

**Status:** Essential — this is the user-facing interface.

#### `command/`
Command dispatch registry. Maps command names to handlers and manages the command execution lifecycle.

**Status:** Essential.

---

### ESSENTIAL — Tools

#### `tool/`
The tool registry and all built-in tool implementations. 40+ tools organized by category:

**File operations:**
- `read` — Read file contents
- `write` — Write files
- `edit` — Targeted text replacement in files
- `multiedit` — Multiple edits in one call
- `ls` — List directory contents
- `glob` — Pattern-based file search
- `grep` — Content search (ripgrep-powered)
- `apply_patch` — Apply unified diffs

**Code intelligence:**
- `bash` — Execute shell commands
- `codesearch` — Semantic code search
- `lsp` — Language Server Protocol queries

**Web:**
- `webfetch` — Fetch web content
- `websearch` — Web search

**Planning:**
- `task` — Track tasks/todos
- `plan` — Enter/exit plan mode
- `question` — Ask the user a question
- `batch` — Execute multiple tools in parallel

**Productivity:**
- `todoread` / `todowrite` — Read and write todo items

**Meta:**
- `skill` — Execute a skill
- `truncate` — Content truncation
- `external-directory` — External directory operations
- `invalid` — Error tool for unsupported operations

**Status:** Essential — tools are the agent's hands.

---

### ESSENTIAL — Infrastructure

#### `server/`
Hono-based HTTP + WebSocket server running on port 4096 (local only). Provides a REST API for all OpenCode operations:

Routes:
- `/session` — Session CRUD
- `/project` — Project management
- `/mcp` — MCP server management
- `/config` — Configuration read/write
- `/provider` — Provider and model listing
- `/permission` — Permission rules
- `/event` — SSE event stream
- `/file` — File operations
- `/global` — Global state
- `/pty` — Pseudo-terminal
- `/question` — Interactive prompts
- `/tui` — TUI state
- `/workspace` — Workspace management
- `/experimental` — Experimental features

Also includes CORS, basic auth, mDNS discovery, and OpenAPI support.

**Status:** Essential — the SDK and TUI both communicate through this server.

#### `storage/`
SQLite database via Drizzle ORM. Database lives at `~/.opencode/opencode.db`.

Tables:
- `sessions` — Conversation sessions
- `messages` — Individual messages in sessions
- `parts` — Message parts (text, tool calls, tool results)
- `projects` — Project directory records
- `accounts` — LLM provider accounts
- `workspaces` — Multi-project workspaces
- `permissions` — Stored permission rules

**Status:** Essential — all state is persisted here.

#### `auth/`
Authentication storage and management. Supports:
- API Key authentication
- OAuth (with access + refresh tokens)
- Well-known token authentication

Credentials stored at `~/.opencode/auth.json` (chmod 0o600 for security).

**Status:** Essential — LLM providers need authentication.

#### `effect/`
Effect.ts runtime integration. Provides:
- Service registry (dependency injection)
- Instance-scoped state management
- Functional error handling patterns
- Async operation management

**Status:** Essential — the entire codebase is built on Effect.ts patterns.

#### `bus/`
Publish/subscribe event bus for inter-module communication. All major state changes (session updates, tool executions, agent events) flow through the event bus, allowing the CLI, TUI, and server to stay in sync.

**Status:** Essential — event-driven architecture backbone.

#### `permission/`
Rule-based access control system. Features:
- Allow / deny / ask rules
- Pattern matching for file paths, commands, tool names
- Rule merging across global, project, and agent scopes
- Interactive approval prompts

**Status:** Essential — security boundary for tool execution.

#### `project/`
Project directory tracking and context management:
- `project.ts` — Project detection and lifecycle
- `instance.ts` — Per-project runtime instance
- `bootstrap.ts` — Project initialization
- `vcs.ts` — Version control (git) integration
- `state.ts` — Project-level state

**Status:** Essential — determines what codebase OpenCode is operating on.

#### `shell/`
Shell execution wrapper. Manages shell processes, captures output, handles signals.

**Status:** Essential — bash tool and PTY depend on this.

#### `pty/`
Pseudo-terminal support via `bun-pty`. Enables running interactive terminal programs within OpenCode sessions.

**Status:** Essential — required for bash tool and interactive shell commands.

#### `filesystem/`
File system operations with proper error handling, path resolution, and platform awareness.

**Status:** Essential — underlies all file-based tools.

#### `env/`
Environment variable management. Loads and validates environment variables for OpenCode's operation.

**Status:** Essential.

#### `util/`
Internal utility library:
- Logging (structured logs to `~/.opencode/logs/`)
- Hashing and ID generation
- Process management utilities
- File system helpers

**Status:** Essential.

#### `format/`
Output formatting for the CLI — colors, tables, markdown rendering in terminal.

**Status:** Essential.

#### `flag/`
CLI flag definitions and parsing utilities shared across commands.

**Status:** Essential.

#### `id/`
ID generation (ULID-based) for sessions, messages, projects.

**Status:** Essential.

#### `installation/`
Version information and installation detection.

**Status:** Essential.

#### `bun/`
Bun-specific utilities and shims.

**Status:** Essential.

---

### IMPORTANT — Enhances the CLI

#### `mcp/`
Model Context Protocol client. Connects OpenCode to MCP servers which expose additional tools and resources.

Supported transports:
- `stdio` — Local MCP servers via stdin/stdout
- `SSE` — Remote MCP servers via Server-Sent Events
- `HTTP` — Remote MCP servers via HTTP

Also handles MCP OAuth flows.

**Status:** Important — enables the full tool ecosystem (filesystem, web, databases, APIs via MCP).

#### `skill/`
Custom skill loader. Discovers SKILL.md files from:
- `.agents/skills/**/SKILL.md`
- `{skill,skills}/**/SKILL.md`

Skills are domain-specific tools defined in Markdown. Examples: git workflow helpers, code review tools, custom generators.

**Status:** Important — enables project-specific and user-defined tools.

#### `plugin/`
Internal plugin loader (distinct from `packages/plugin/`). Loads npm-installed plugins:
- Discovers plugins listed in `opencode.jsonc`
- Runs plugin hooks at appropriate lifecycle points
- Built-in plugins: CodexAuth, CopilotAuth, GitLabAuth

**Status:** Important — extensibility for auth providers and custom tools.

#### `acp/`
Agent Client Protocol implementation. JSON-RPC over stdio interface that lets IDE clients (like Zed) control OpenCode:
- Session lifecycle management
- Message exchange
- Event streaming

**Status:** Important — standard IDE integration protocol.

#### `snapshot/`
Session state compression and restoration. Allows large sessions to be compacted and efficiently restored.

**Status:** Important — enables long-running sessions without context overflow.

#### `control-plane/`
Multi-project workspace routing. Manages workspace-level state and SSE notifications across multiple active projects.

**Status:** Important — supports multi-project workflows.

#### `worktree/`
Git worktree support. Allows OpenCode to create isolated git worktrees for working on tasks without affecting the main branch.

**Status:** Important — enables safe parallel task execution.

#### `question/`
Interactive user prompt system. Allows the agent to pause and ask the user a question during execution.

**Status:** Important — agent-user interaction.

#### `prompt/`
Prompt management utilities — template loading, variable substitution, prompt assembly helpers.

**Status:** Important.

#### `patch/`
Diff/patch application utilities. Used by the `apply_patch` tool.

**Status:** Important.

---

### OPTIONAL — Can Be Disabled Without Breaking Core

#### `lsp/`
Full Language Server Protocol 3.17 implementation:
- Go-to-definition
- Symbol search
- Hover information
- Diagnostic reporting
- Code completion
- Document synchronization

Used by the `lsp` tool for code intelligence features.

**Status:** Optional — enhances code understanding but the agent works without it.

#### `ide/`
Zed editor integration stub (~2KB). Minimal Zed-specific integration that goes beyond ACP.

**Status:** Optional — harmless to keep given its tiny size.

#### `share/`
Session/output sharing feature (implementation incomplete).

**Status:** Optional — not production-ready, can be left as-is or removed later.

#### `cli/cmd/tui/`
Full interactive TUI using Ink (React for terminals):
- Full-screen mode with panels, dialogs, keyboard navigation
- Agent/model/session/MCP/skill/theme dialogs
- Command palette

The `run` command's inline mode works without the TUI. The TUI is activated via `opencode tui` or `opencode run --tui`.

**Status:** Optional — inline mode is the default and doesn't need it.

---

## Architecture Diagram

```
User
 │
 ▼
bin/opencode (entry)
 │
 ├── cli/cmd/run.ts        ← "opencode run" (inline mode, default)
 ├── cli/cmd/tui/app.tsx   ← "opencode tui" (full TUI, optional)
 ├── cli/cmd/serve.ts      ← "opencode serve" (server mode)
 └── cli/cmd/acp.ts        ← IDE integration (JSON-RPC stdio)
          │
          ▼
     agent/agent.ts        ← Multi-agent orchestration
          │
          ├── session/     ← Conversation persistence + prompt building
          ├── provider/    ← LLM abstraction (20+ providers)
          ├── tool/        ← 40+ built-in tools
          ├── mcp/         ← External tool ecosystem
          ├── permission/  ← Access control
          └── config/      ← Configuration
          │
          ▼
     server/server.ts      ← Local HTTP API (port 4096)
          │
          ▼
     storage/              ← SQLite (sessions, messages, projects)
```
