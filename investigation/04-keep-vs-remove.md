# Keep vs Remove — Decision Matrix

Consolidated decision matrix for every component in the OpenCode project, evaluated for inclusion in a standalone terminal CLI coding agent.

---

## Root Level

| Item | Decision | Reason |
|------|----------|--------|
| `packages/` | **KEEP** | Contains all active code |
| `.opencode/` | **KEEP** | Project self-configuration (agents, tools, themes) |
| `.agents/` | **KEEP** | Skill definitions for running OpenCode on itself |
| `patches/` | **KEEP** | Required dependency fixes (3 patches) |
| `specs/` | **KEEP** | API specification — architectural reference |
| `script/` | **KEEP** | Release automation |
| `.husky/` | **KEEP** | Git hooks for code quality |
| `.vscode/` | **KEEP** | Editor settings |
| `package.json` | **KEEP** | Monorepo root — already clean |
| `turbo.json` | **KEEP** | Turborepo pipeline — already clean |
| `tsconfig.json` | **KEEP** | TypeScript config |
| `bunfig.toml` / `bun.lock` | **KEEP** | Bun config and lockfile |
| `AGENTS.md` / `README.md` / `LICENSE` / `CONTRIBUTING.md` / `SECURITY.md` | **KEEP** | Project docs |
| `install` | **KEEP** | End-user install script |
| `STATS.md` | **KEEP** | Auto-generated stats |
| `.editorconfig` / `.prettierignore` / `.gitignore` | **KEEP** | Tooling config |
| `.turbo/` | **KEEP** | Build cache (auto-managed) |
| `.venv/` | **KEEP** | Local Python tooling |
| `external/` | **REMOVE** | Contains only empty `mistral-vibe/` placeholder |
| `node_modules/` | **KEEP** | Installed dependencies (gitignored) |
| `.env` | **KEEP** | Local env vars (gitignored) |

### Already Deleted from Working Tree (Stage These)

| Item | Was |
|------|-----|
| `archive/` | Old Malibu Python project — unrelated to OpenCode |
| `deepagents_cli/` | deepagents CLI project — unrelated |
| `external/deepagents_cli/` | Copy of deepagents CLI |
| `external/kimi-cli/` | kimi-cli project — unrelated |
| `distribution/zed/` | Zed editor extension distribution |
| `docs/` | Old documentation |
| `.pre-commit-config.yaml` | Python pre-commit config (Python project removed) |
| `.python-version` | Python version pin (Python project removed) |
| `.typos.toml` | Typos linter config |
| `CHANGELOG.md` | Changelog |
| `action.yml` | GitHub Action |

---

## Packages

| Package | Decision | Reason |
|---------|----------|--------|
| `packages/opencode/` | **KEEP** | Core CLI engine — cannot remove |
| `packages/sdk/js/` | **KEEP** | Programmatic SDK — lightweight, useful for server deployment |
| `packages/plugin/` | **KEEP** | Plugin framework — enables third-party extensions |
| `packages/util/` | **KEEP** | Required dependency of opencode and plugin |
| `packages/script/` | **KEEP** | Build/release tooling |
| `packages/app/` | REMOVED ✓ | Web application — not needed for CLI |
| `packages/console/` | REMOVED ✓ | Console UI — TUI is in opencode/src/cli/cmd/tui/ |
| `packages/containers/` | REMOVED ✓ | Docker configs — not needed for CLI |
| `packages/desktop/` | REMOVED ✓ | Desktop app — not needed |
| `packages/desktop-electron/` | REMOVED ✓ | Electron wrapper — not needed |
| `packages/docs/` | REMOVED ✓ | Documentation website — not runtime |
| `packages/enterprise/` | REMOVED ✓ | Enterprise features — not needed for personal use |
| `packages/extensions/` | REMOVED ✓ | IDE extension framework — not needed |
| `packages/function/` | REMOVED ✓ | Serverless functions — not needed for local CLI |
| `packages/identity/` | REMOVED ✓ | Branding assets — not runtime code |
| `packages/slack/` | REMOVED ✓ | Slack bot — not needed for terminal CLI |
| `packages/storybook/` | REMOVED ✓ | UI development tool — removed with UI package |
| `packages/ui/` | REMOVED ✓ | SolidJS UI library — for web/desktop apps (removed) |
| `packages/web/` | REMOVED ✓ | Web interface — not needed for terminal CLI |

---

## packages/opencode/src Modules

| Module | Decision | Reason |
|--------|----------|--------|
| `agent/` | **KEEP** | Core — agent orchestration |
| `cli/` | **KEEP** | Core — command-line interface |
| `server/` | **KEEP** | Core — local HTTP server |
| `session/` | **KEEP** | Core — conversation persistence |
| `config/` | **KEEP** | Core — configuration system |
| `auth/` | **KEEP** | Core — LLM authentication |
| `provider/` | **KEEP** | Core — LLM abstraction layer |
| `tool/` | **KEEP** | Core — tool registry and implementations |
| `mcp/` | **KEEP** | Core — MCP tool ecosystem |
| `permission/` | **KEEP** | Core — security/access control |
| `project/` | **KEEP** | Core — working directory context |
| `storage/` | **KEEP** | Core — SQLite persistence |
| `effect/` | **KEEP** | Core — Effect.ts runtime |
| `bus/` | **KEEP** | Core — event bus |
| `command/` | **KEEP** | Core — command dispatch |
| `shell/` | **KEEP** | Core — shell execution |
| `pty/` | **KEEP** | Core — pseudo-terminal |
| `filesystem/` | **KEEP** | Core — file operations |
| `env/` | **KEEP** | Core — environment variables |
| `util/` | **KEEP** | Core — logging, hashing, utilities |
| `format/` | **KEEP** | Core — output formatting |
| `flag/` | **KEEP** | Core — CLI flags |
| `id/` | **KEEP** | Core — ID generation |
| `installation/` | **KEEP** | Core — version info |
| `bun/` | **KEEP** | Core — Bun utilities |
| `skill/` | **KEEP** | Important — custom tools |
| `plugin/` | **KEEP** | Important — plugin loader |
| `acp/` | **KEEP** | Important — IDE integration |
| `snapshot/` | **KEEP** | Important — context optimization |
| `control-plane/` | **KEEP** | Important — multi-project support |
| `worktree/` | **KEEP** | Important — git worktrees |
| `question/` | **KEEP** | Important — interactive prompts |
| `prompt/` | **KEEP** | Important — prompt templates |
| `patch/` | **KEEP** | Important — diff/patch application |
| `lsp/` | **KEEP** | Optional — code intelligence (keep, enhances quality) |
| `ide/` | **KEEP** | Optional — tiny stub (~2KB), harmless |
| `share/` | **KEEP** | Optional — incomplete, harmless to keep |
| `cli/cmd/tui/` | **KEEP** | Optional — full TUI (inline mode works without it) |

**Summary:** All source modules in `packages/opencode/src/` should be kept. None are wasteful — the agent is already cleanly structured with each module serving a specific purpose.

---

## Patches

| Patch | Decision | Reason |
|-------|----------|--------|
| `@ai-sdk/xai@2.0.51.patch` | **KEEP** | Fix for XAI provider |
| `@openrouter/ai-sdk-provider@1.5.4.patch` | **KEEP** | Fix for OpenRouter provider |
| `solid-js@1.9.10.patch` | **INVESTIGATE** | SolidJS patch — check if still needed after removing SolidJS-dependent packages |

---

## Summary

**Current state:** The project is nearly clean already. The 5 active packages are exactly the right ones. The main remaining work is:

1. Stage the already-deleted files (hundreds of files from archive/, deepagents_cli/, external/kimi-cli/, etc.)
2. Remove `external/mistral-vibe/` (empty placeholder)
3. Verify the `solid-js` patch is still needed or can be removed
4. Commit
