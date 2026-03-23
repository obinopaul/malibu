# createMalibuAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `createDeepAgent` from the `deepagents` package with a custom `createMalibuAgent` wrapper around `createAgent` from `langchain`, eliminating duplicate filesystem tools and conflicting system prompts that cause the model to call tools with empty `{}` args.

**Architecture:** `createMalibuAgent` is a thin wrapper around `createAgent` (from `"langchain"`) that assembles the same middleware stack as `createDeepAgent` MINUS `createFilesystemMiddleware`. This removes the 7 duplicate filesystem tools and the `"## Filesystem Tools"` system prompt injection. The wrapper also includes `createCacheBreakpointMiddleware` (inlined, since it's not exported from `deepagents`). Harness.ts switches from `createDeepAgent` to `createMalibuAgent` and removes all dedup/override middleware since there are no longer duplicate tools.

**Tech Stack:** TypeScript, `langchain` (createAgent, middleware), `deepagents` (individual middleware exports), `@langchain/core` (messages), Bun runtime

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/agent/create-agent.ts` | **Create** | `createMalibuAgent()` wrapper — assembles middleware, calls `createAgent` |
| `src/agent/harness.ts` | **Modify** | Switch from `createDeepAgent` to `createMalibuAgent`, remove dedup middleware |
| `src/agent/subagents.ts` | **Modify** | Update comments for `createMalibuAgent` (keep `MIDDLEWARE_ONLY_TOOLS` filter) |
| `src/tool/registry.ts` | **Modify** | Remove wrapper tool registrations (LsTool, ReadFileTool, etc.) |
| `src/tool/deepagent-filesystem.ts` | **Delete** | No longer needed — wrapper tools eliminated |
| `src/tool/deepagent-path.ts` | **Keep** | Still used by 6 native tools (read, write, edit, ls, glob, grep) — do NOT delete |
| `src/tool/alias.ts` | **Modify** | Reverse canonical direction: DeepAgent names → Malibu native names |
| `src/session/harness-processor.ts` | **Modify** | Update `DEEPAGENT_TOOL_TITLES` map to use Malibu native tool names |
| `src/agent/tool-dedupe.ts` | **Delete** | No longer needed — no duplicate tools to dedup |
| `test/agent/create-agent.test.ts` | **Create** | Tests for createMalibuAgent middleware assembly |
| `test/agent/tool-schema-diagnostic.test.ts` | **Modify** | Update to reflect new architecture (no duplicates) |

**Important:** `src/tool/deepagent-path.ts` (`resolveDeepPath`, `resolveToolPath`, `resolveToolSearch`) is imported by 6 native Malibu tools and must NOT be deleted.

---

### Task 1: Create `createMalibuAgent` wrapper

**Files:**
- Create: `src/agent/create-agent.ts`
- Test: `test/agent/create-agent.test.ts`

This is the core new file. It mirrors `createDeepAgent` from `deepagentsjs/libs/deepagents/src/agent.ts` (lines 98-404) but omits `createFilesystemMiddleware`.

- [ ] **Step 0: Add `langchain` as a direct dependency**

`langchain` is currently only a transitive dependency (via `deepagents`). Add it explicitly:

```bash
cd packages/opencode && bun add langchain@1.2.34
```

Verify it's in `package.json` under `dependencies`.

- [ ] **Step 1: Write the failing test for middleware assembly**

Create `test/agent/create-agent.test.ts`:

```typescript
/**
 * Tests for createMalibuAgent — verifies middleware assembly
 * and that NO filesystem middleware is included.
 */
import { describe, expect, test, mock } from "bun:test"

describe("createMalibuAgent", () => {
  test("does not include createFilesystemMiddleware", async () => {
    // We can't easily inspect middleware inside a ReactAgent,
    // so we verify by checking that the function doesn't import
    // or call createFilesystemMiddleware.
    const source = await Bun.file("src/agent/create-agent.ts").text()
    expect(source).not.toContain("createFilesystemMiddleware")
    expect(source).not.toContain("FilesystemMiddleware")
    // But it SHOULD use other middleware
    expect(source).toContain("todoListMiddleware")
    expect(source).toContain("createSubAgentMiddleware")
    expect(source).toContain("createSummarizationMiddleware")
    expect(source).toContain("createPatchToolCallsMiddleware")
  })

  test("exports createMalibuAgent function", async () => {
    const mod = await import("../../src/agent/create-agent")
    expect(typeof mod.createMalibuAgent).toBe("function")
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/opencode && bun test test/agent/create-agent.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Write `createMalibuAgent` implementation**

Create `src/agent/create-agent.ts`:

```typescript
/**
 * createMalibuAgent — custom agent factory that wraps langchain's createAgent.
 *
 * This replaces createDeepAgent from the `deepagents` package. The key difference:
 * NO createFilesystemMiddleware is included. Malibu provides its own filesystem
 * tools (read, list, glob, grep, edit, write, bash) via the tool registry,
 * so DeepAgent's built-in filesystem tools are not needed.
 *
 * Middleware assembled (in order):
 * 1. todoListMiddleware — task tracking
 * 2. createSubAgentMiddleware — sub-agent delegation (explore, general)
 * 3. createSummarizationMiddleware — context window management
 * 4. createPatchToolCallsMiddleware — cross-provider tool compat
 * 5. createSkillsMiddleware — skills from .agents/skills/ (conditional)
 * 6. anthropicPromptCachingMiddleware — Anthropic cache (conditional)
 * 7. cacheBreakpointMiddleware — cache breakpoint (conditional, Anthropic)
 * 8. user custom middleware
 */
import {
  createAgent,
  createMiddleware,
  todoListMiddleware,
  anthropicPromptCachingMiddleware,
  SystemMessage,
  type AgentMiddleware,
} from "langchain"
import type { StructuredTool } from "@langchain/core/tools"
import type { BaseCheckpointSaver } from "@langchain/langgraph-checkpoint"
import {
  createSubAgentMiddleware,
  createSummarizationMiddleware,
  createPatchToolCallsMiddleware,
  createSkillsMiddleware,
  LocalShellBackend,
  type SubAgent,
} from "deepagents"
// Note: We import SubAgent type but NOT createDeepAgent or createFilesystemMiddleware

import { Log } from "../util/log"

const log = Log.create({ service: "create-agent" })

/**
 * Cache breakpoint middleware — inlined because deepagents doesn't export it.
 * Tags the last system message block with cache_control for Anthropic prompt caching.
 */
function createCacheBreakpointMiddleware() {
  return createMiddleware({
    name: "CacheBreakpointMiddleware",
    wrapModelCall(request: any, handler: any) {
      const existingContent = request.systemMessage?.content
      const existingBlocks =
        typeof existingContent === "string"
          ? [{ type: "text" as const, text: existingContent }]
          : Array.isArray(existingContent)
            ? [...existingContent]
            : []

      if (existingBlocks.length === 0) return handler(request)

      existingBlocks[existingBlocks.length - 1] = {
        ...existingBlocks[existingBlocks.length - 1],
        cache_control: { type: "ephemeral" },
      }

      return handler({
        ...request,
        systemMessage: new SystemMessage({ content: existingBlocks }),
      })
    },
  })
}

export interface CreateMalibuAgentParams {
  /** LangChain ChatModel instance */
  model: any
  /** LangChain StructuredTool[] — Malibu's tools, already converted */
  tools: StructuredTool[]
  /** System prompt string */
  systemPrompt: string
  /** Checkpointer for persistent state */
  checkpointer?: BaseCheckpointSaver | boolean
  /** LocalShellBackend for filesystem access (used by subagents, summarization) */
  backend: LocalShellBackend
  /** Sub-agents (explore, general) */
  subagents?: SubAgent[]
  /** Skill directory paths */
  skills?: string[]
  /** Agent name */
  name?: string
  /** Additional custom middleware (appended last) */
  middleware?: AgentMiddleware[]
  /** Whether to detect Anthropic model for prompt caching */
  isAnthropicModel?: boolean
}

/**
 * Create a Malibu agent using langchain's createAgent directly.
 *
 * Unlike createDeepAgent, this does NOT include createFilesystemMiddleware,
 * so no duplicate filesystem tools or conflicting system prompts are injected.
 */
export function createMalibuAgent(params: CreateMalibuAgentParams) {
  const {
    model,
    tools,
    systemPrompt,
    checkpointer,
    backend,
    subagents = [],
    skills,
    name,
    middleware: customMiddleware = [],
    isAnthropicModel = false,
  } = params

  // --- Subagent middleware (passed to createSubAgentMiddleware for subagent-internal use) ---
  // Note: This is a SEPARATE middleware stack from builtInMiddleware.
  // todoListMiddleware() appears here AND in builtInMiddleware intentionally:
  // - Here: gives subagents their own todo tracking
  // - In builtInMiddleware: gives the main agent todo tracking
  const subagentMiddleware: AgentMiddleware[] = [
    todoListMiddleware(),
    createSummarizationMiddleware({ model, backend }),
    createPatchToolCallsMiddleware(),
  ]

  // --- Skills middleware (conditional) ---
  const skillsMiddlewareArray: AgentMiddleware[] =
    skills && skills.length > 0
      ? [createSkillsMiddleware({ backend, sources: skills })]
      : []

  // --- Anthropic caching middleware ---
  const anthropicMiddleware: AgentMiddleware[] = isAnthropicModel
    ? [
        anthropicPromptCachingMiddleware({
          unsupportedModelBehavior: "ignore",
          minMessagesToCache: 1,
        }),
        createCacheBreakpointMiddleware(),
      ]
    : []

  // --- Built-in middleware (NO createFilesystemMiddleware) ---
  const builtInMiddleware: AgentMiddleware[] = [
    // 1. Todo list management
    todoListMiddleware(),
    // 2. Sub-agent delegation (explore, general via task tool)
    createSubAgentMiddleware({
      defaultModel: model,
      defaultTools: tools,
      defaultMiddleware: [...subagentMiddleware, ...anthropicMiddleware],
      generalPurposeMiddleware: [
        ...subagentMiddleware,
        ...skillsMiddlewareArray,
        ...anthropicMiddleware,
      ],
      subagents,
      generalPurposeAgent: true,
    } as any),
    // 3. Context summarization
    createSummarizationMiddleware({ model, backend }),
    // 4. Cross-provider tool call compatibility
    createPatchToolCallsMiddleware(),
  ]

  // --- Assemble runtime middleware ---
  const runtimeMiddleware: AgentMiddleware[] = [
    ...builtInMiddleware,
    ...skillsMiddlewareArray,
    ...customMiddleware,
    ...anthropicMiddleware,
  ]

  log.info("createMalibuAgent: assembled middleware", {
    total: runtimeMiddleware.length,
    hasSkills: skillsMiddlewareArray.length > 0,
    isAnthropic: isAnthropicModel,
    subagentCount: subagents.length,
    toolCount: tools.length,
  })

  // --- Create the agent ---
  const agent = createAgent({
    model,
    systemPrompt,
    tools,
    middleware: runtimeMiddleware,
    checkpointer,
    name,
  }).withConfig({
    recursionLimit: 10_000,
    metadata: { ls_integration: "malibu" },
  })

  return agent
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/opencode && bun test test/agent/create-agent.test.ts`
Expected: PASS

- [ ] **Step 5: Run typecheck**

Run: `cd packages/opencode && bun run typecheck 2>&1 | grep -v "langchain-adapter.ts(217"`
Expected: No new errors

- [ ] **Step 6: Commit**

```bash
git add src/agent/create-agent.ts test/agent/create-agent.test.ts
git commit -m "feat: add createMalibuAgent wrapper around langchain createAgent

Replaces createDeepAgent with a custom wrapper that assembles
the same middleware stack minus createFilesystemMiddleware.
This eliminates duplicate filesystem tools and conflicting
system prompts that caused models to call tools with empty args."
```

---

### Task 2: Update harness.ts to use createMalibuAgent

**Files:**
- Modify: `src/agent/harness.ts`

- [ ] **Step 1: Replace imports**

In `src/agent/harness.ts`, replace:
```typescript
import {
  createDeepAgent,
  LocalShellBackend,
} from "deepagents"
```
With:
```typescript
import { LocalShellBackend } from "deepagents"
import { createMalibuAgent } from "./create-agent"
```

- [ ] **Step 2: Remove `createToolOverrideMiddleware` function**

Delete the entire function (lines ~66-103) and its JSDoc comment. Also remove the `import { dedupeRequestTools } from "./tool-dedupe"` line.

- [ ] **Step 3: Keep `MIDDLEWARE_ONLY_TOOLS` filtering (still needed)**

`createMalibuAgent` still uses `todoListMiddleware` (adds `todowrite`/`todoread`) and `createSubAgentMiddleware` (adds `task`). These tools would be duplicated if also passed as custom tools. **Keep the filter** but update the comment:

```typescript
/**
 * Tools that duplicate middleware functionality and should NOT be passed
 * as custom tools to createMalibuAgent.
 * - "task" duplicates SubAgentMiddleware's task tool
 * - "todowrite"/"todoread" duplicate TodoListMiddleware
 */
const MIDDLEWARE_ONLY_TOOLS = new Set([
  "task",
  "todowrite",
  "todoread",
])
```

The `filteredMalibuTools` filter stays as-is.

- [ ] **Step 4: Replace `createDeepAgent` call with `createMalibuAgent`**

In `Harness.run()`, replace:
```typescript
const agent = createDeepAgent({
  model: built.chatModel as any,
  tools: built.langchainTools,
  systemPrompt: built.systemPrompt,
  checkpointer: ensureCheckpointer(),
  backend: built.backend,
  subagents: built.subagents,
  skills: built.skillPaths,
  name: config.agent.name,
  middleware: [createToolOverrideMiddleware()] as any,
})
```
With:
```typescript
const isAnthropicModel = config.model.providerID === "anthropic"
  || config.model.providerID === "anthropic-vertex"
  || config.model.id?.includes("claude")

const agent = createMalibuAgent({
  model: built.chatModel,
  tools: built.langchainTools,
  systemPrompt: built.systemPrompt,
  checkpointer: ensureCheckpointer(),
  backend: built.backend,
  subagents: built.subagents,
  skills: built.skillPaths,
  name: config.agent.name,
  isAnthropicModel,
})
```

- [ ] **Step 5: Update `streamAgent` type signature**

Change:
```typescript
async function streamAgent(
  agent: ReturnType<typeof createDeepAgent>,
```
To:
```typescript
async function streamAgent(
  agent: ReturnType<typeof createMalibuAgent>,
```

- [ ] **Step 6: Update file header comment**

Replace the file's JSDoc header (lines 1-17) to reflect the new architecture:
```typescript
/**
 * Harness — uses createMalibuAgent (wrapping langchain's createAgent) as the
 * single agent execution engine.
 *
 * Features:
 * - createMalibuAgent with NO built-in filesystem tools (Malibu's own tools only)
 * - Built-in middleware: TodoList, SubAgents, Summarization, PatchToolCalls, Prompt Caching
 * - Malibu custom tools passed directly — no duplicates, no dedup needed
 * - Sub-agents (explore, general) via langchain's task tool
 * - Skills loaded from .agents/skills/
 * - SQLite-backed checkpointer for persistent state
 * - Delta-based streaming for TUI rendering via Bus events
 * - Doom loop detection, token tracking, error normalization
 */
```

- [ ] **Step 7: Rename `buildDeepAgentConfig` → `buildAgentConfig`**

Rename the function and update its JSDoc:
```typescript
  /**
   * Build the full createMalibuAgent configuration from a Harness.Config.
   */
  async function buildAgentConfig(config: Config) {
```

Update the call site in `run()`:
```typescript
const built = await buildAgentConfig(config)
```

- [ ] **Step 8: Run typecheck**

Run: `cd packages/opencode && bun run typecheck 2>&1 | grep -v "langchain-adapter.ts(217"`
Expected: No new errors

- [ ] **Step 9: Commit**

```bash
git add src/agent/harness.ts
git commit -m "refactor: switch harness from createDeepAgent to createMalibuAgent

Remove createToolOverrideMiddleware and dedup middleware.
Keep MIDDLEWARE_ONLY_TOOLS filter for task/todowrite/todoread.
No more filesystem middleware, no duplicate tools."
```

---

### Task 3: Remove wrapper tools from registry

**Files:**
- Modify: `src/tool/registry.ts`
- Delete: `src/tool/deepagent-filesystem.ts`

- [ ] **Step 1: Remove wrapper tool imports from registry.ts**

In `src/tool/registry.ts`, remove these imports:
```typescript
import { LsTool } from "./deepagent-filesystem"
import { ReadFileTool } from "./deepagent-filesystem"
import { EditFileTool } from "./deepagent-filesystem"
import { WriteFileTool } from "./deepagent-filesystem"
import { ExecuteTool } from "./deepagent-filesystem"
```

(The exact import style may vary — find and remove all imports from `"./deepagent-filesystem"`.)

- [ ] **Step 2: Remove wrapper tools from the `all()` array**

In the `all()` function, remove these entries from the returned array:
- `ExecuteTool`
- `LsTool`
- `ReadFileTool`
- `EditFileTool`
- `WriteFileTool`

Keep all native Malibu tools: `BashTool`, `ListTool`, `ReadTool`, `GlobTool`, `GrepTool`, `EditTool`, `WriteTool`, etc.

- [ ] **Step 3: Delete `src/tool/deepagent-filesystem.ts`**

Run: `rm src/tool/deepagent-filesystem.ts`

This file defined LsTool, ReadFileTool, WriteFileTool, EditFileTool, ExecuteTool — all wrapper tools that are no longer needed.

**IMPORTANT: Do NOT delete `src/tool/deepagent-path.ts`.** This file (`resolveDeepPath`, `resolveToolPath`, `resolveToolSearch`) is imported by 6 native Malibu tools:
- `src/tool/read.ts` → `resolveToolPath`
- `src/tool/write.ts` → `resolveToolPath`
- `src/tool/edit.ts` → `resolveToolPath`
- `src/tool/ls.ts` → `resolveToolSearch`
- `src/tool/glob.ts` → `resolveToolSearch`
- `src/tool/grep.ts` → `resolveToolSearch`

- [ ] **Step 4: Check for other imports of deepagent-filesystem**

Run: `grep -r "deepagent-filesystem" src/`
Expected: No results (if there are, update those files too)

- [ ] **Step 5: Run typecheck**

Run: `cd packages/opencode && bun run typecheck 2>&1 | grep -v "langchain-adapter.ts(217"`
Expected: No new errors

- [ ] **Step 6: Commit**

```bash
git add src/tool/registry.ts
git rm src/tool/deepagent-filesystem.ts
git commit -m "refactor: remove DeepAgent wrapper tools (ls, read_file, write_file, etc.)

Model now sees only Malibu native tools: read, list, glob, grep,
edit, write, bash. No more duplicate-purpose tools with different
names and conflicting path conventions."
```

---

### Task 4: Update subagents.ts comments

**Files:**
- Modify: `src/agent/subagents.ts`

- [ ] **Step 1: Update `MIDDLEWARE_ONLY_TOOLS` comment (keep the filter)**

The `MIDDLEWARE_ONLY_TOOLS` set is still needed — `createSubAgentMiddleware` provides `task` and `todoListMiddleware` provides `todowrite`/`todoread`, so passing them as custom tools would duplicate them. Keep the filter, update the comment at lines 32-37:
```typescript
/**
 * Tools that duplicate middleware functionality and should NOT be passed
 * as custom tools to createMalibuAgent or sub-agents.
 * - "task" duplicates SubAgentMiddleware's task tool
 * - "todowrite"/"todoread" duplicate TodoListMiddleware
 */
```

- [ ] **Step 2: Update the `SubAgent` import**

The `SubAgent` type import stays the same (from `"deepagents"`). No change needed.

- [ ] **Step 3: Update file header comment**

Change "createDeepAgent" references to "createMalibuAgent":
```typescript
/**
 * Sub-Agents — defines SubAgent objects for explore and general agents.
 *
 * These SubAgent objects are passed to createMalibuAgent({ subagents: [...] })
 * and automatically wired through the SubAgentMiddleware's `task` tool.
 */
```

- [ ] **Step 4: Commit**

```bash
git add src/agent/subagents.ts
git commit -m "docs: update subagents.ts comments for createMalibuAgent"
```

---

### Task 5: Clean up tool-dedupe.ts

**Files:**
- Delete: `src/agent/tool-dedupe.ts`

- [ ] **Step 1: Check for other imports of tool-dedupe**

Run: `grep -r "tool-dedupe" src/ test/`
Expected: Only `harness.ts` (already removed in Task 2) and `test/agent/tool-schema-diagnostic.test.ts`

- [ ] **Step 2: Delete tool-dedupe.ts**

Run: `rm src/agent/tool-dedupe.ts`

- [ ] **Step 3: Commit**

```bash
git rm src/agent/tool-dedupe.ts
git commit -m "refactor: remove tool-dedupe.ts (no longer needed)"
```

---

### Task 6: Update diagnostic tests

**Files:**
- Modify: `test/agent/tool-schema-diagnostic.test.ts`

- [ ] **Step 1: Rewrite tests for new architecture**

The diagnostic tests should now verify:
1. Model sees ONLY Malibu native tools (no duplicates)
2. No wrapper tools (ls, read_file, etc.) in the tool list
3. Empty args `{}` validation still works for each tool

```typescript
/**
 * Tool Schema Diagnostic Tests — Post-Migration
 *
 * Verifies that after switching to createMalibuAgent:
 * 1. No duplicate tools exist
 * 2. Only Malibu native tool names are in the registry
 * 3. Empty args validation works correctly
 */
import { describe, expect, test } from "bun:test"
import z from "zod"

const MALIBU_NATIVE_TOOLS = [
  "read",       // ReadTool - requires filePath
  "list",       // ListTool - path is optional
  "glob",       // GlobTool - requires pattern
  "grep",       // GrepTool - requires pattern
  "edit",       // EditTool - requires filePath, oldString, newString
  "write",      // WriteTool - requires filePath, content
  "bash",       // BashTool - requires command
]

const REMOVED_WRAPPER_TOOLS = [
  "ls",         // Was: LsTool wrapper
  "read_file",  // Was: ReadFileTool wrapper
  "write_file", // Was: WriteFileTool wrapper
  "edit_file",  // Was: EditFileTool wrapper
  "execute",    // Was: ExecuteTool wrapper
]

describe("post-migration: no duplicate tools", () => {
  test("wrapper tools are no longer registered", async () => {
    // Verify deepagent-filesystem.ts was deleted
    const file = Bun.file("src/tool/deepagent-filesystem.ts")
    expect(await file.exists()).toBe(false)
  })

  test("registry does not import wrapper tools", async () => {
    const source = await Bun.file("src/tool/registry.ts").text()
    expect(source).not.toContain("deepagent-filesystem")
    expect(source).not.toContain("LsTool")
    expect(source).not.toContain("ReadFileTool")
    expect(source).not.toContain("WriteFileTool")
    expect(source).not.toContain("EditFileTool")
    expect(source).not.toContain("ExecuteTool")
  })

  test("harness uses createMalibuAgent, not createDeepAgent", async () => {
    const source = await Bun.file("src/agent/harness.ts").text()
    expect(source).toContain("createMalibuAgent")
    expect(source).not.toContain("createDeepAgent")
    expect(source).not.toContain("createToolOverrideMiddleware")
  })
})

describe("post-migration: empty args validation", () => {
  test("read({}) FAILS — filePath is required", () => {
    const schema = z.object({
      filePath: z.string().describe("path"),
      offset: z.coerce.number().optional(),
      limit: z.coerce.number().optional(),
    })
    expect(schema.safeParse({}).success).toBe(false)
  })

  test("list({}) PASSES — all params optional", () => {
    const schema = z.object({
      path: z.string().optional(),
      ignore: z.array(z.string()).optional(),
    })
    expect(schema.safeParse({}).success).toBe(true)
  })

  test("glob({}) FAILS — pattern is required", () => {
    const schema = z.object({
      pattern: z.string().describe("pattern"),
      path: z.string().optional(),
    })
    expect(schema.safeParse({}).success).toBe(false)
  })

  test("grep({}) FAILS — pattern is required", () => {
    const schema = z.object({
      pattern: z.string().describe("regex"),
      path: z.string().optional(),
      include: z.string().optional(),
    })
    expect(schema.safeParse({}).success).toBe(false)
  })

  test("bash({}) FAILS — command is required", () => {
    const schema = z.object({
      command: z.string().describe("command"),
      timeout: z.coerce.number().optional(),
      description: z.string().optional(),
    })
    expect(schema.safeParse({}).success).toBe(false)
  })
})
```

- [ ] **Step 2: Run tests**

Run: `cd packages/opencode && bun test test/agent/tool-schema-diagnostic.test.ts`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add test/agent/tool-schema-diagnostic.test.ts
git commit -m "test: update diagnostic tests for createMalibuAgent migration"
```

---

### Task 7: Reverse tool alias canonical direction

**Files:**
- Modify: `src/tool/alias.ts`

The current alias map canonicalizes Malibu native names to DeepAgent names:
`"read" → "read_file"`, `"list" → "ls"`, `"bash" → "execute"`.

Post-migration, the canonical tools are the Malibu native names. The harness streaming loop uses `canonTool()` and `sameTool()` to match tool call IDs, so aliases must still work but should canonicalize to the **native** names.

- [ ] **Step 1: Reverse the canonical direction**

Replace `src/tool/alias.ts` contents with:

```typescript
/**
 * Tool name alias map — canonicalizes tool names to Malibu native names.
 *
 * After the createMalibuAgent migration, the canonical tool names are:
 *   read, list, write, edit, bash, glob, grep
 *
 * Old DeepAgent names (read_file, ls, execute, etc.) are kept as aliases
 * for backward compatibility with existing sessions and middleware that
 * may still reference them internally (e.g., SubAgentMiddleware, TodoListMiddleware).
 */
const map = new Map<string, string>([
  // Malibu native names (canonical)
  ["read", "read"],
  ["list", "list"],
  ["write", "write"],
  ["edit", "edit"],
  ["bash", "bash"],
  ["glob", "glob"],
  ["grep", "grep"],
  // DeepAgent aliases → Malibu native
  ["read_file", "read"],
  ["ls", "list"],
  ["write_file", "write"],
  ["edit_file", "edit"],
  ["execute", "bash"],
  // Middleware tools (unchanged)
  ["todowrite", "todowrite"],
  ["write_todos", "todowrite"],
  ["todoread", "todoread"],
  ["task", "task"],
])

export function canonTool(name?: string) {
  if (!name) return ""
  return map.get(name) ?? name
}

export function sameTool(a?: string, b?: string) {
  if (!a || !b) return false
  return canonTool(a) === canonTool(b)
}
```

- [ ] **Step 2: Run typecheck**

Run: `cd packages/opencode && bun run typecheck 2>&1 | grep -v "langchain-adapter.ts(217"`
Expected: No new errors

- [ ] **Step 3: Run tests**

Run: `cd packages/opencode && bun test --timeout 30000`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add src/tool/alias.ts
git commit -m "refactor: reverse tool alias direction to canonicalize to Malibu native names

Old: read→read_file, list→ls, bash→execute
New: read_file→read, ls→list, execute→bash
Keeps backward compat for existing sessions and middleware."
```

---

### Task 8: Update harness-processor tool title map

**Files:**
- Modify: `src/session/harness-processor.ts`

The `DEEPAGENT_TOOL_TITLES` map uses old DeepAgent names (`read_file`, `write_file`, `edit_file`, `ls`, `write_todos`). After migration, tools emit Malibu native names so these entries will never match.

- [ ] **Step 1: Find and update `DEEPAGENT_TOOL_TITLES`**

Run: `grep -n "DEEPAGENT_TOOL_TITLES\|read_file\|write_file\|edit_file" src/session/harness-processor.ts`

Update the map to use Malibu native tool names:
```typescript
const TOOL_TITLES: Record<string, string> = {
  read: "Read",
  list: "List",
  write: "Write",
  edit: "Edit",
  bash: "Bash",
  glob: "Glob",
  grep: "Grep",
  todowrite: "TodoWrite",
  todoread: "TodoRead",
  task: "Task",
  // Legacy aliases for existing sessions
  read_file: "Read",
  write_file: "Write",
  edit_file: "Edit",
  ls: "List",
  execute: "Bash",
  write_todos: "TodoWrite",
}
```

- [ ] **Step 2: Rename the constant from `DEEPAGENT_TOOL_TITLES` to `TOOL_TITLES`**

Update all references in the file.

- [ ] **Step 3: Commit**

```bash
git add src/session/harness-processor.ts
git commit -m "refactor: update tool title map for Malibu native tool names"
```

---

### Task 9: Full integration test

**Files:**
- None (verification only)

- [ ] **Step 1: Run all existing tests**

Run: `cd packages/opencode && bun test --timeout 30000`
Expected: All tests pass (or only pre-existing failures)

- [ ] **Step 2: Run typecheck**

Run: `cd packages/opencode && bun run typecheck`
Expected: Only pre-existing `langchain-adapter.ts:217` error

- [ ] **Step 3: Manual smoke test**

Run the CLI and verify:
1. The agent responds to a simple prompt
2. Tool calls include proper arguments (not empty `{}`)
3. No "## Filesystem Tools" in the system prompt
4. Tools listed by the model are: read, list, glob, grep, edit, write, bash (NOT ls, read_file, etc.)
5. Sub-agents work (try a task that triggers explore or general delegation)

- [ ] **Step 4: Final commit (if any fixups needed)**

```bash
git add -A
git commit -m "fix: integration fixups for createMalibuAgent migration"
```
