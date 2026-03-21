# Final Architecture — Terminal CLI Agent

This document describes the slim, focused architecture that remains after the cleanup.

---

## What Remains

```
opencode/
├── .agents/                ← Agent skill definitions (SKILL.md files)
├── .husky/                 ← Git hooks
├── .opencode/              ← Project self-configuration
│   ├── opencode.jsonc      ← Provider, permission, tool config
│   ├── agent/              ← Built-in agent definitions
│   ├── command/            ← Custom CLI commands
│   ├── glossary/           ← Domain terminology
│   ├── themes/             ← UI themes
│   └── tool/               ← Custom tool definitions
├── packages/
│   ├── opencode/           ← CORE: Terminal CLI engine
│   │   ├── bin/opencode    ← Executable entry point
│   │   ├── src/            ← ~40 source modules (see below)
│   │   ├── migration/      ← Database migrations
│   │   └── specs/          ← Package-level API specs
│   ├── sdk/js/             ← Public JS/TS SDK
│   │   └── src/            ← client.ts, server.ts, index.ts
│   ├── plugin/             ← Public plugin framework SDK
│   │   └── src/            ← Plugin, Hooks, ToolDefinition types
│   ├── util/               ← Shared utilities
│   └── script/             ← Build/release scripts
├── patches/                ← 3 dependency patches
├── script/                 ← Root release automation
├── specs/                  ← project.md API spec
├── package.json            ← Monorepo root (clean workspaces)
├── turbo.json              ← Turborepo pipeline (clean)
├── tsconfig.json           ← TypeScript config
├── bunfig.toml / bun.lock  ← Bun config
└── install                 ← End-user install script
```

---

## Core Engine: packages/opencode/src/

```
src/
├── index.ts               ← Entry: bootstrap → Yargs CLI
│
├── AGENT LAYER
│   ├── agent/             ← Multi-agent orchestration
│   │   └── agent.ts       ← Built-in agents: build, plan, general, explore
│   ├── session/           ← Conversation persistence + prompt building
│   │   ├── index.ts       ← Session CRUD + event emission
│   │   ├── prompt.ts      ← Full LLM prompt assembly (68KB)
│   │   ├── llm.ts         ← LLM call + streaming
│   │   └── compaction.ts  ← Context window optimization
│   └── provider/          ← LLM provider abstraction
│       ├── provider.ts    ← 20+ provider support
│       └── models.ts      ← Model catalog
│
├── CLI LAYER
│   └── cli/
│       ├── cmd/run.ts     ← "opencode run" — inline output mode (default)
│       ├── cmd/serve.ts   ← "opencode serve" — server mode
│       ├── cmd/acp.ts     ← IDE integration via JSON-RPC
│       ├── cmd/tui/       ← Optional: full Ink TUI (fullscreen mode)
│       └── cmd/[others]   ← 20+ additional commands
│
├── TOOL LAYER
│   ├── tool/              ← 40+ built-in tools
│   │   ├── read, write, edit, glob, grep, ls, apply_patch
│   │   ├── bash, codesearch, lsp
│   │   ├── webfetch, websearch
│   │   ├── task, plan, question, batch
│   │   └── todoread, todowrite, skill
│   ├── mcp/               ← MCP client (external tools + resources)
│   └── skill/             ← Custom SKILL.md tool loader
│
├── INFRASTRUCTURE
│   ├── server/            ← Hono HTTP+WebSocket (port 4096)
│   ├── storage/           ← SQLite via Drizzle ORM
│   ├── auth/              ← LLM provider authentication
│   ├── config/            ← Configuration system
│   ├── permission/        ← Rule-based access control
│   ├── project/           ← Project directory + git context
│   ├── plugin/            ← npm plugin loader
│   ├── effect/            ← Effect.ts runtime
│   ├── bus/               ← Pub/sub event bus
│   └── command/           ← Command dispatch registry
│
└── UTILITIES
    ├── shell/, pty/       ← Shell + pseudo-terminal
    ├── filesystem/        ← File operations
    ├── format/            ← Output formatting
    ├── util/              ← Logging, hashing, process mgmt
    ├── env/, flag/, id/   ← Environment, CLI flags, ID gen
    ├── acp/               ← Agent Client Protocol
    ├── snapshot/          ← Session state compression
    ├── control-plane/     ← Multi-project workspace routing
    ├── worktree/          ← Git worktree support
    ├── lsp/               ← Language Server Protocol
    ├── patch/             ← Diff/patch application
    └── question/          ← Interactive user prompts
```

---

## Data Flow: A Single User Request

```
1. User runs: opencode run "add unit tests to auth.ts"
                    │
2. cli/cmd/run.ts   │  parse args, load config, find project
                    │
3. agent/agent.ts   │  select "build" agent, assemble context
                    │
4. session/         │  load history, build system prompt + instructions
  prompt.ts         │
                    │
5. provider/        │  call LLM (e.g. Claude claude-opus-4-6)
  provider.ts       ├──► LLM API ──► stream tokens back
                    │
6. agent/agent.ts   │  parse tool calls from response
                    │
7. permission/      │  check: is this tool call allowed?
  index.ts          │  (allow/deny/ask user)
                    │
8. tool/registry    │  execute tool:
                    │  e.g. tool/read → read auth.ts
                    │       tool/write → write auth.test.ts
                    │       tool/bash → run tests
                    │
9. session/         │  append tool results to message history
                    │
10. Repeat 4–9      │  until agent calls stop/complete
                    │
11. cli/cmd/run.ts  │  display final output inline to terminal
```

---

## Persistence

All state lives in `~/.opencode/`:

```
~/.opencode/
├── opencode.db     ← SQLite database (sessions, messages, projects)
├── auth.json       ← LLM provider credentials (chmod 0o600)
└── logs/           ← Structured log files
```

---

## Extension Points

OpenCode can be extended without modifying core code:

### 1. Skills (SKILL.md)
Create `.agents/skills/my-tool/SKILL.md` in any project. Auto-discovered and registered as agent tools.

### 2. npm Plugins
Install a plugin that implements the `@opencode-ai/plugin` interface. Add it to `opencode.jsonc`. The plugin can add tools, auth providers, and lifecycle hooks.

### 3. MCP Servers
Configure any MCP-compatible server in `opencode.jsonc`. OpenCode connects via stdio, SSE, or HTTP and exposes the MCP server's tools to the agent.

### 4. Custom Agents
Define agent personalities in `opencode.jsonc` or `.opencode/agent/` markdown files. Each agent gets its own system prompt, tool allowlist, and model settings.

---

## Future: LangChain/LangGraph Migration

When migrating the agent layer to LangChain/LangGraph, the key integration points are:

| Current | LangChain/LangGraph Equivalent |
|---------|-------------------------------|
| `agent/agent.ts` | LangGraph `StateGraph` with agent nodes |
| `session/prompt.ts` | LangChain `ChatPromptTemplate` |
| `provider/provider.ts` | LangChain `BaseChatModel` / model wrappers |
| `tool/registry.ts` | LangChain `Tool` / `StructuredTool` definitions |
| `session/compaction.ts` | LangGraph message trimming / summarization |
| Effect.ts service layer | LangGraph state channels |
| `bus/` event bus | LangGraph streaming events |

The `server/`, `storage/`, `config/`, `auth/`, `permission/`, `mcp/`, and `cli/` modules are **independent of the agent framework** and can remain as-is during the migration.
