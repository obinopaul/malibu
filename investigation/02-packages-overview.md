# Packages Overview

This file documents every package that was or is in `packages/`, its purpose, current status, and verdict.

---

## Currently Active Packages

These 5 packages exist in the working tree right now.

### `packages/opencode/` — CORE — KEEP

**npm name:** `opencode`
**Version:** 1.2.27
**Entry point:** `./bin/opencode` (CLI executable)

The main terminal CLI agent. Contains everything needed to run OpenCode as a standalone command-line tool: the agent loop, CLI commands, local HTTP server, session management, LLM provider abstraction, tool registry, MCP integration, plugin loader, config system, auth, permission system, and more.

See [03-packages-opencode-src.md](./03-packages-opencode-src.md) for a full breakdown of its 40+ source modules.

**Tech stack:**
- Bun runtime
- Effect.ts for functional programming and service management
- Drizzle ORM + SQLite for persistence
- Hono for the local HTTP server
- Ink (React for terminals) for the optional TUI
- Vercel AI SDK for LLM provider abstraction

---

### `packages/sdk/js/` — PUBLIC SDK — KEEP

**npm name:** `@opencode-ai/sdk`
**Entry:** `src/index.ts`

The public TypeScript/JavaScript SDK for programmatically using OpenCode. Provides:
- `createOpencodeClient()` — Connect to a running OpenCode server and call its REST API
- `createOpencodeServer()` — Spawn a new OpenCode server process
- `createOpencode()` — Combined factory for standalone use

Generated types in `src/gen/` come from the OpenAPI spec automatically.

**Why keep:** Useful if deploying OpenCode as a backend service and connecting other systems to it. Zero production dependencies — very lightweight.

---

### `packages/plugin/` — PLUGIN FRAMEWORK SDK — KEEP

**npm name:** `@opencode-ai/plugin`
**Entry:** `src/index.ts`

The public plugin framework SDK. Defines the types third-party plugin authors use:
- `Plugin` — function `(input: PluginInput) => Hooks`
- `Hooks` — extensible hook interface (events, tools, auth, chat hooks)
- `ToolDefinition` — typed helper for creating tools
- `PluginInput` — context given to a plugin (client, project, directory, shell)

**Key distinction vs `packages/opencode/src/plugin/`:**
- **This package** = the public API surface that plugin *authors* code against
- **`packages/opencode/src/plugin/`** = the internal runtime that *loads* and *executes* those plugins

**Dependencies:** `@opencode-ai/sdk` + `zod` (only 2 lightweight dependencies)

---

### `packages/util/` — SHARED UTILITIES — KEEP

**npm name:** `@opencode-ai/util`
**Private:** true (internal package, not published)

Shared TypeScript utility functions and types. Required by `packages/opencode` and `packages/plugin`. Contains Zod-based helpers and common utilities.

---

### `packages/script/` — BUILD TOOLS — KEEP

**npm name:** `@opencode-ai/script`
**Private:** true (internal tooling)

Build and release automation used by the monorepo's CI/CD pipeline. Mirrors the root `script/` folder in terms of purpose.

---

## Deleted Packages (Need to Stage)

These packages existed in a previous commit but are no longer in the working tree. All are correctly removed — they were peripheral to the terminal CLI.

### `packages/app/` — WEB APP — REMOVED ✓
SolidJS-based web application frontend. Not needed for terminal CLI.

### `packages/console/` — CONSOLE UI — REMOVED ✓
Console/terminal UI packages (multiple sub-packages). Was an alternative rendering layer. The terminal UI is now handled inside `packages/opencode/src/cli/cmd/tui/` using Ink.

### `packages/containers/` — DOCKER — REMOVED ✓
Docker/container configurations. Not needed for the CLI itself.

### `packages/desktop/` — DESKTOP APP — REMOVED ✓
Desktop application (non-Electron). Not needed.

### `packages/desktop-electron/` — ELECTRON — REMOVED ✓
Electron wrapper for a desktop GUI version of OpenCode. Not needed for terminal CLI.

### `packages/docs/` — DOCS WEBSITE — REMOVED ✓
Astro/Starlight-based documentation website. Static site, not runtime code.

### `packages/enterprise/` — ENTERPRISE — REMOVED ✓
Enterprise features (SSO, audit logs, etc.). Not needed for personal/open-source terminal CLI use.

### `packages/extensions/` — EXTENSIONS FRAMEWORK — REMOVED ✓
Extensions framework (likely for IDE extensions). Not needed.

### `packages/function/` — SERVERLESS FUNCTIONS — REMOVED ✓
Cloud serverless function utilities. Not needed for local terminal CLI.

### `packages/identity/` — BRANDING ASSETS — REMOVED ✓
Identity/branding images and assets. Not runtime code.

### `packages/slack/` — SLACK BOT — REMOVED ✓
Slack bot integration that lets users create OpenCode sessions from Slack threads. Useful for teams but not for a standalone terminal CLI agent.

### `packages/storybook/` — COMPONENT SHOWCASE — REMOVED ✓
Storybook for UI component development/documentation. Development tooling for the deleted UI package.

### `packages/ui/` — UI COMPONENT LIBRARY — REMOVED ✓
SolidJS UI component library (buttons, inputs, themes, etc.) for the web and desktop apps. Not needed since those apps are removed.

### `packages/web/` — WEB INTERFACE — REMOVED ✓
Web-based interface for OpenCode. Not needed.

---

## Key Architectural Note: The Plugin Stack

```
npm package by third-party author
        ↓  implements
packages/plugin/          ← Public API: Plugin, Hooks, ToolDefinition
        ↓  loaded by
packages/opencode/src/plugin/  ← Internal loader: discovers + executes plugins at runtime
        ↓  runs inside
packages/opencode/        ← Core CLI engine
```

The `packages/plugin/` SDK is the contract between OpenCode core and the plugin ecosystem. Third-party plugin authors depend on `@opencode-ai/plugin`. The CLI itself loads those plugins via the internal `src/plugin/` module.
