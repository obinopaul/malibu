# OpenCode Investigation

This folder documents a systematic investigation of the OpenCode project structure — what each folder and package does, why it exists, and whether it is needed for a standalone terminal-based CLI coding agent.

## Goal

Slim down the project to its essential terminal CLI components, removing everything peripheral (web apps, desktop apps, Slack bots, IDE extensions, etc.), and prepare the codebase for a future migration of the agent layer to LangChain/LangGraph.

## Files

| File | Covers |
|------|--------|
| [01-root-structure.md](./01-root-structure.md) | Root-level directories and files — what each is, keep/remove verdict |
| [02-packages-overview.md](./02-packages-overview.md) | All `packages/` subdirectories — purpose, status, verdict |
| [03-packages-opencode-src.md](./03-packages-opencode-src.md) | Deep dive into every module inside `packages/opencode/src/` |
| [04-keep-vs-remove.md](./04-keep-vs-remove.md) | Consolidated decision matrix across the whole project |
| [05-final-architecture.md](./05-final-architecture.md) | Final slim architecture for the terminal CLI agent |

## Summary of Findings

**OpenCode** is a TypeScript/Bun monorepo that originally contained a full suite of products:
- Terminal CLI agent (core)
- Web app and documentation site
- Desktop app (Electron)
- Console UI
- Slack bot
- VSCode / Zed extensions
- Enterprise features
- SolidJS UI component library
- Storybook

**Most peripheral packages have already been deleted** from the working tree. The project has naturally converged to just the terminal CLI essentials.

### What Remains (active packages)

| Package | Role |
|---------|------|
| `packages/opencode/` | Core CLI engine — the entire terminal agent |
| `packages/sdk/js/` | Public JS/TS SDK for programmatic access |
| `packages/plugin/` | Public plugin framework SDK |
| `packages/util/` | Shared utilities (required dependency) |
| `packages/script/` | Build and release automation scripts |

### What Was Already Removed

All other packages (app, console, desktop, desktop-electron, docs, enterprise, extensions, function, identity, slack, storybook, ui, web) have been deleted from the working tree and need their deletions staged/committed.
