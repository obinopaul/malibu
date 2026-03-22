# DeepAgent Harness Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the custom `createReactAgent`-based harness with `createDeepAgent` from the `deepagents` npm package as the single agent execution engine, removing the dual-engine toggle.

**Architecture:** `createDeepAgent()` becomes the sole agent loop. Malibu's existing `Tool.Info` instances are converted to LangChain `DynamicStructuredTool` (already done via `langchain-adapter.ts`) and passed as custom tools. Sub-agents (explore, general) become DeepAgent `SubAgent` objects wired through `createSubAgentMiddleware`. The existing SQLite checkpointer is passed to `createDeepAgent({ checkpointer })`. A `LocalShellBackend` provides filesystem access. The existing Bus event system is preserved for TUI streaming by processing `streamEvents()` output. The dual-engine config toggle is removed — `createDeepAgent` is always used.

**Tech Stack:** `deepagents@1.8.4`, `@langchain/langgraph`, `@langchain/core`, existing Malibu tool/permission/session infrastructure

---

## File Structure

### Files to Rewrite
- `packages/opencode/src/agent/harness.ts` — Replace `createReactAgent` with `createDeepAgent`. Keep Bus events, token tracking, error normalization. Remove manual tool streaming loop (DeepAgent handles it).
- `packages/opencode/src/agent/subagents.ts` — Replace `createReactAgent` sub-agents with DeepAgent `SubAgent` objects. Remove `runSubAgent()` internal runner.

### Files to Modify
- `packages/opencode/src/session/prompt.ts` (lines 601-602, 650-844) — Remove dual-engine toggle. Make DeepAgent the only path. Remove sub-agent dispatch logic (DeepAgent handles it via `task` tool).
- `packages/opencode/src/config/config.ts` (line ~1228) — Remove `experimental.engine` config option.
- `packages/opencode/src/session/harness-processor.ts` — Update to work with new Harness API (minimal changes — Bus events remain the same).

### Files to Keep Unchanged
- `packages/opencode/src/agent/checkpointer.ts` — SQLite checkpointer already implements `BaseCheckpointSaver`, directly compatible with `createDeepAgent({ checkpointer })`.
- `packages/opencode/src/provider/unified.ts` — Still creates `BaseChatModel` instances, directly compatible with `createDeepAgent({ model })`.
- `packages/opencode/src/provider/langchain-factory.ts` — Unchanged.
- `packages/opencode/src/provider/ai-sdk-adapter.ts` — Unchanged.
- `packages/opencode/src/tool/langchain-adapter.ts` — `toLangChainTools()` returns `DynamicStructuredTool[]`, directly compatible with `createDeepAgent({ tools })`.
- `packages/opencode/src/agent/permission-middleware.ts` — Keep doom loop detection. Permission callback stays for tool-level HITL.
- `packages/opencode/src/agent/compaction-middleware.ts` — Keep for token state utilities. DeepAgent's `SummarizationMiddleware` replaces compaction sub-agent.
- `packages/opencode/src/agent/agent.ts` — Agent definitions unchanged.

### Files to Delete
- None. All files are either rewritten or kept.

---

## Task Breakdown

### Task 1: Rewrite `harness.ts` — Core DeepAgent Integration

**Files:**
- Rewrite: `packages/opencode/src/agent/harness.ts`

This is the biggest task. Replace `createReactAgent` with `createDeepAgent`, keep Bus event streaming, keep token usage tracking, keep error normalization.

- [ ] **Step 1: Update imports**

Replace the `createReactAgent` import and add `deepagents` imports:

```typescript
// REMOVE:
import { createReactAgent } from "@langchain/langgraph/prebuilt"

// ADD:
import {
  createDeepAgent,
  LocalShellBackend,
  createSummarizationMiddleware,
  createSkillsMiddleware,
  createMemoryMiddleware,
  type SubAgent,
  type DeepAgent,
} from "deepagents"
```

Keep all existing LangChain message imports (`HumanMessage`, `AIMessage`, etc.), Bus imports, and Malibu imports.

- [ ] **Step 2: Add DeepAgent configuration builder**

Add a new function `buildDeepAgentConfig()` that constructs the `CreateDeepAgentParams` from a `Harness.Config`. This function:

1. Creates the LangChain `BaseChatModel` via `UnifiedProvider.create()`
2. Converts Malibu tools to LangChain tools via `toLangChainTools()`
3. Builds the system prompt string
4. Creates a `LocalShellBackend` rooted at the project working directory
5. Builds the sub-agent array (imported from rewritten `subagents.ts` — Task 2)
6. Configures `interruptOn` from the agent's permission ruleset for tools that need HITL
7. Sets up skills paths from `.agents/skills/`
8. Returns the full `CreateDeepAgentParams` object

```typescript
import { Instance } from "../project/instance"
import { Skill } from "../skill"

async function buildDeepAgentConfig(config: Config) {
  const chatModel = await UnifiedProvider.create(config.model, {
    temperature: config.agent.temperature,
    streaming: true,
    metadata: {
      sessionID: config.sessionID,
      agent: config.agent.name,
    },
  })

  const bridge: ToolBridgeContext = {
    sessionID: config.sessionID,
    messageID: config.messageID,
    agent: config.agent.name,
    abort: config.abort,
    messages: config.messages,
    onMetadata: config.onMetadata,
    onPermission: config.onPermission,
  }
  const langchainTools = await toLangChainTools(config.tools, bridge, config.agent)

  const systemPrompt = config.system.filter(Boolean).join("\n")

  // LocalShellBackend for real filesystem access
  const backend = new LocalShellBackend({ root: Instance.worktree })

  // Build skill paths
  const skillDirs = await Skill.dirs()
  const skillPaths = skillDirs.map(d => d + "/")

  // Build sub-agents (from subagents.ts)
  const subagents = await buildSubAgents(config)

  // Build interruptOn from permission ruleset for HITL
  const interruptOn = buildInterruptConfig(config.agent, config.permission)

  return {
    chatModel,
    langchainTools,
    systemPrompt,
    backend,
    skillPaths,
    subagents,
    interruptOn,
  }
}
```

- [ ] **Step 3: Rewrite `Harness.run()` to use `createDeepAgent`**

Replace the current `run()` that calls `createReactAgent` with one that calls `createDeepAgent`:

```typescript
export async function run(config: Config): Promise<Result> {
  log.info("harness.run", {
    session: config.sessionID,
    agent: config.agent.name,
    model: config.model.id,
  })

  const built = await buildDeepAgentConfig(config)

  const agent = createDeepAgent({
    model: built.chatModel,
    tools: built.langchainTools,
    systemPrompt: built.systemPrompt,
    checkpointer: ensureCheckpointer(),
    backend: built.backend,
    subagents: built.subagents,
    skills: built.skillPaths.length > 0 ? built.skillPaths : undefined,
    interruptOn: built.interruptOn,
    name: config.agent.name,
  })

  const langchainMessages = convertMessages(config.messages)
  const threadId = `${config.sessionID}-${config.messageID}`

  return streamAgent(agent, { messages: langchainMessages }, threadId, config)
}
```

- [ ] **Step 4: Update `streamAgent()` type signature**

Change the first parameter type from `ReturnType<typeof createReactAgent>` to `DeepAgent<any>`:

```typescript
async function streamAgent(
  agent: DeepAgent<any>,
  input: any,
  threadId: string,
  config: Config,
): Promise<Result> {
  // ... rest stays the same
}
```

The stream processing loop (text deltas, tool calls, token usage, doom loop detection) remains unchanged because `DeepAgent` extends `ReactAgent` and supports the same `stream()` API with `streamMode: "messages"`.

- [ ] **Step 5: Update `Harness.resume()` to use `createDeepAgent`**

```typescript
export async function resume(config: Config, resumeValue: any): Promise<Result> {
  const threadId = `${config.sessionID}-${config.messageID}`
  const built = await buildDeepAgentConfig(config)

  const agent = createDeepAgent({
    model: built.chatModel,
    tools: built.langchainTools,
    systemPrompt: built.systemPrompt,
    checkpointer: ensureCheckpointer(),
    backend: built.backend,
    subagents: built.subagents,
    skills: built.skillPaths.length > 0 ? built.skillPaths : undefined,
    interruptOn: built.interruptOn,
    name: config.agent.name,
  })

  return streamAgent(agent, new Command({ resume: resumeValue }), threadId, config)
}
```

- [ ] **Step 6: Add `buildInterruptConfig()` helper**

Converts Malibu's permission ruleset to DeepAgent's `interruptOn` format. Tools with `"ask"` permission become interrupt targets:

```typescript
function buildInterruptConfig(
  agent: Agent.Info,
  sessionPermission?: Permission.Ruleset,
): Record<string, boolean> | undefined {
  const merged = sessionPermission
    ? Permission.merge(agent.permission, sessionPermission)
    : agent.permission

  const interruptOn: Record<string, boolean> = {}
  let hasAny = false

  for (const rule of merged) {
    if (rule.action === "ask") {
      // Map permission names to tool names where applicable
      interruptOn[rule.permission] = true
      hasAny = true
    }
  }

  return hasAny ? interruptOn : undefined
}
```

- [ ] **Step 7: Verify Bus events are still emitted**

The existing `streamAgent()` loop processes `AIMessageChunk` and `ToolMessage` events from the stream. Since `DeepAgent.stream()` produces the same event types (it extends `ReactAgent`), all Bus event publishing (`Event.TextDelta`, `Event.ToolStart`, `Event.ToolEnd`, etc.) continues to work. No changes needed to the stream processing loop.

Verify this by checking the `streamAgent()` function still handles:
- `AIMessageChunk` → `Event.TextDelta`, tool_call_chunks → `Event.ToolStart`
- `ToolMessage` → `Event.ToolEnd`, doom loop check
- `AIMessage` → text/usage fallback
- `GraphInterrupt` error → `status: "interrupted"`

- [ ] **Step 8: Remove unused imports**

Remove `createReactAgent` import. Keep `Command` import (used in `resume()`).

- [ ] **Step 9: Verify the file compiles**

Run: `cd packages/opencode && npx tsc --noEmit src/agent/harness.ts`
Expected: No errors (or only pre-existing errors from other files).

- [ ] **Step 10: Commit**

```bash
git add packages/opencode/src/agent/harness.ts
git commit -m "feat: rewrite harness to use createDeepAgent from deepagents package

Replaces createReactAgent with createDeepAgent as the single agent loop.
Adds LocalShellBackend, skills, sub-agents, and interruptOn config.
Preserves Bus event streaming, token tracking, and error normalization."
```

---

### Task 2: Rewrite `subagents.ts` — DeepAgent SubAgent Objects

**Files:**
- Rewrite: `packages/opencode/src/agent/subagents.ts`

Replace `createReactAgent`-based sub-agents with DeepAgent `SubAgent` interface objects. These are passed to `createDeepAgent({ subagents: [...] })` and automatically wired through the `task` tool.

- [ ] **Step 1: Replace imports**

```typescript
// REMOVE:
import { createReactAgent } from "@langchain/langgraph/prebuilt"
import { HumanMessage, AIMessage } from "@langchain/core/messages"
import type { BaseChatModel } from "@langchain/core/language_models/chat_models"
import type { DynamicStructuredTool } from "@langchain/core/tools"
import { Harness } from "./harness"
import { UnifiedProvider } from "../provider/unified"
import { CompactionMiddleware } from "./compaction-middleware"

// ADD:
import type { SubAgent } from "deepagents"
```

Keep: `Agent`, `toLangChainTools`/`ToolBridgeContext`, `Provider`, `Log`, `Tool` types.

- [ ] **Step 2: Rewrite as SubAgent builder functions**

Replace the namespace with functions that return `SubAgent` objects:

```typescript
import type { SubAgent } from "deepagents"
import type { DynamicStructuredTool } from "@langchain/core/tools"
import { Agent } from "./agent"
import { toLangChainTools, type ToolBridgeContext } from "../tool/langchain-adapter"
import { Log } from "../util/log"
import type { Tool } from "../tool/tool"
import type { SessionID, MessageID } from "../session/schema"
import type { MessageV2 } from "../session/message-v2"

const log = Log.create({ service: "subagents" })

const EXPLORE_TOOLS = new Set([
  "grep", "glob", "read", "bash", "webfetch", "websearch", "codesearch", "list",
])

const GENERAL_DENIED_TOOLS = new Set(["todoread", "todowrite"])

export interface SubAgentBuildContext {
  sessionID: SessionID
  messageID: MessageID
  allTools: Tool.Info[]
  messages: MessageV2.WithParts[]
  abort: AbortSignal
  onMetadata?: (input: { title?: string; metadata?: Record<string, any> }) => void
  onPermission?: (input: any) => Promise<void>
}

/**
 * Build DeepAgent SubAgent objects for the explore and general agents.
 * These are passed to createDeepAgent({ subagents: [...] }).
 */
export async function buildSubAgents(
  ctx: SubAgentBuildContext,
): Promise<SubAgent[]> {
  const subagents: SubAgent[] = []

  // Explore sub-agent
  const exploreAgent = await Agent.get("explore")
  if (exploreAgent) {
    const exploreTools = ctx.allTools.filter(t => EXPLORE_TOOLS.has(t.id))
    const bridge: ToolBridgeContext = {
      sessionID: ctx.sessionID,
      messageID: ctx.messageID,
      agent: "explore",
      abort: ctx.abort,
      messages: ctx.messages,
      onMetadata: ctx.onMetadata,
      onPermission: ctx.onPermission,
    }
    const lcTools = await toLangChainTools(exploreTools, bridge, exploreAgent)

    subagents.push({
      name: "explore",
      description: exploreAgent.description ?? "Fast agent for exploring codebases.",
      systemPrompt: exploreAgent.prompt ?? "You are an explore agent. Search and read code to answer questions.",
      tools: lcTools,
    })
  }

  // General sub-agent
  const generalAgent = await Agent.get("general")
  if (generalAgent) {
    const generalTools = ctx.allTools.filter(t => !GENERAL_DENIED_TOOLS.has(t.id))
    const bridge: ToolBridgeContext = {
      sessionID: ctx.sessionID,
      messageID: ctx.messageID,
      agent: "general",
      abort: ctx.abort,
      messages: ctx.messages,
      onMetadata: ctx.onMetadata,
      onPermission: ctx.onPermission,
    }
    const lcTools = await toLangChainTools(generalTools, bridge, generalAgent)

    subagents.push({
      name: "general",
      description: generalAgent.description ?? "General-purpose agent for multi-step tasks.",
      systemPrompt: generalAgent.prompt ?? "You are a general-purpose agent. Execute complex tasks.",
      tools: lcTools,
    })
  }

  log.info("built sub-agents", { count: subagents.length })
  return subagents
}
```

- [ ] **Step 3: Export `buildSubAgents` from the module**

The function is already exported. Verify `harness.ts` imports it:

```typescript
import { buildSubAgents } from "./subagents"
```

- [ ] **Step 4: Remove the old `SubAgents` namespace, `SubAgentConfig`, `SubAgentResult`, `runSubAgent()`, and `dispatch()`**

These are no longer needed — DeepAgent's `task` tool handles sub-agent dispatch automatically. The `@agent` dispatch in `prompt.ts` will also be removed (Task 3).

- [ ] **Step 5: Verify the file compiles**

Run: `cd packages/opencode && npx tsc --noEmit src/agent/subagents.ts`

- [ ] **Step 6: Commit**

```bash
git add packages/opencode/src/agent/subagents.ts
git commit -m "feat: rewrite subagents as DeepAgent SubAgent objects

Replaces createReactAgent-based sub-agents with SubAgent interface objects.
DeepAgent's task tool handles dispatch automatically."
```

---

### Task 3: Remove Dual-Engine Toggle from `prompt.ts`

**Files:**
- Modify: `packages/opencode/src/session/prompt.ts` (lines 601-897)

Remove the `if (useLangGraph)` / `else` branch. Make the DeepAgent (harness) path the only path. Remove sub-agent dispatch logic (DeepAgent handles it via `task` tool).

- [ ] **Step 1: Remove the engine toggle variable**

Delete line 601-602:
```typescript
// DELETE:
const cfg = await Config.get()
const useLangGraph = cfg.experimental?.engine === "langgraph"
```

- [ ] **Step 2: Remove the `if (useLangGraph) { ... } else { ... }` branch structure**

Keep ONLY the LangGraph path content (lines 650-844), but simplified:
- Remove sub-agent dispatch logic (lines 756-844) — DeepAgent handles `@agent` via `task` tool
- Keep: HarnessProcessor creation, tool filtering, MCP tool injection, StructuredOutput tool, permission callback
- Remove: The entire AI SDK `else` branch (lines 845-897)

The simplified code becomes:

```typescript
// Create harness processor
const harnessProc = HarnessProcessor.create({
  assistantMessage: assistantMessage,
  sessionID,
  model,
  abort,
})
using _ = defer(() => InstructionPrompt.clear(harnessProc.message.id))

// Filter tools through permissions
const toolInfos = await ToolRegistry.all()
const mergedPermission = Permission.merge(agent.permission, session.permission ?? [])
const disabledTools = Permission.disabled(
  toolInfos.map((t) => t.id),
  mergedPermission,
)
const filteredTools = toolInfos.filter((t) => {
  if (disabledTools.has(t.id)) return false
  if (lastUser.tools?.[t.id] === false) return false
  return true
})

// Add MCP tools (existing code lines 674-727, unchanged)
// ... MCP tool injection ...

// Inject StructuredOutput tool if needed (existing code lines 729-746, unchanged)
// ... StructuredOutput injection ...

// Create permission callback
const onPermission = PermissionMiddleware.createPermissionCallback({
  sessionID,
  messageID: harnessProc.message.id,
  agent,
  sessionPermission: session.permission,
})

// Process via DeepAgent harness (no sub-agent dispatch — DeepAgent handles it)
result = await harnessProc.process({
  agent,
  permission: session.permission,
  system,
  messages: msgs,
  tools: filteredTools,
  abort,
  onPermission,
})
```

- [ ] **Step 3: Remove unused imports**

Remove `SessionProcessor` import if no longer used (it was the AI SDK path processor). Remove `SubAgents` import. Remove `Config` import if only used for the engine toggle.

Check which imports are still needed after the removal.

- [ ] **Step 4: Remove the `resolveTools()` function call and related AI SDK helpers**

If `resolveTools()` was only used in the AI SDK path, it can be removed. Check if it's used elsewhere in the file first.

- [ ] **Step 5: Verify the file compiles**

Run: `cd packages/opencode && npx tsc --noEmit src/session/prompt.ts`

- [ ] **Step 6: Commit**

```bash
git add packages/opencode/src/session/prompt.ts
git commit -m "feat: remove dual-engine toggle, use DeepAgent as sole engine

Removes the AI SDK engine path and config.experimental.engine toggle.
DeepAgent harness is now the only execution path.
Sub-agent dispatch is handled by DeepAgent's built-in task tool."
```

---

### Task 4: Remove `experimental.engine` Config Option

**Files:**
- Modify: `packages/opencode/src/config/config.ts` (~line 1228)

- [ ] **Step 1: Find and remove the engine config**

Search for `engine` in the experimental config schema. Remove the `engine: z.enum(["ai-sdk", "langgraph"]).optional()` field.

- [ ] **Step 2: Verify no other code references `experimental.engine`**

Run: `grep -r "experimental.*engine\|engine.*langgraph\|engine.*ai-sdk" packages/opencode/src/`

Remove any remaining references.

- [ ] **Step 3: Commit**

```bash
git add packages/opencode/src/config/config.ts
git commit -m "chore: remove experimental.engine config option

DeepAgent is now the sole execution engine, no toggle needed."
```

---

### Task 5: Update `harness-processor.ts` for New Harness API

**Files:**
- Modify: `packages/opencode/src/session/harness-processor.ts`

Minimal changes — the Bus events (`Harness.Event.TextDelta`, `ToolStart`, `ToolEnd`) remain the same. The `Harness.run()` call signature is unchanged. The processor should still work.

- [ ] **Step 1: Verify `HarnessProcessor` still compiles**

The processor calls `Harness.run()` which returns `Harness.Result` — same interface. Bus event subscriptions are unchanged. Token usage extraction is unchanged.

Run: `cd packages/opencode && npx tsc --noEmit src/session/harness-processor.ts`

- [ ] **Step 2: If there are type errors, fix them**

Possible issues:
- If `Harness.Config` interface changed (it shouldn't)
- If the result shape changed (it shouldn't)

- [ ] **Step 3: Commit (only if changes were needed)**

```bash
git add packages/opencode/src/session/harness-processor.ts
git commit -m "fix: update harness-processor for new DeepAgent harness API"
```

---

### Task 6: Full Compilation Check

**Files:** All modified files

- [ ] **Step 1: Run full TypeScript compilation**

```bash
cd packages/opencode && npx tsc --noEmit 2>&1 | head -50
```

Expected: No new errors introduced by our changes.

- [ ] **Step 2: Fix any compilation errors**

Address any type mismatches between `deepagents` types and our code.

Common issues to watch for:
- `SubAgent` interface may require `systemPrompt` as `string | SystemMessage` — use string
- `DeepAgent` generic type params — use `DeepAgent<any>` if exact inference is complex
- `LocalShellBackend` constructor may need specific options — check the API
- `createDeepAgent` may need `model` as `BaseLanguageModel | string` — our `BaseChatModel` extends `BaseLanguageModel`

- [ ] **Step 3: Run existing tests**

```bash
cd packages/opencode && bun test test/agent/ 2>&1 | tail -20
```

Fix any test failures.

- [ ] **Step 4: Commit fixes**

```bash
git add -A
git commit -m "fix: resolve compilation errors from DeepAgent migration"
```

---

### Task 7: Smoke Test — End-to-End Verification

**Files:** None (testing only)

- [ ] **Step 1: Build the project**

```bash
cd packages/opencode && bun run build
```

- [ ] **Step 2: Verify the agent starts**

```bash
cd packages/opencode && bun run src/cli/cmd/serve.ts
```

Check that the server starts without errors.

- [ ] **Step 3: Check that imports resolve**

```bash
cd packages/opencode && node -e "const d = require('deepagents'); console.log(Object.keys(d).slice(0, 10))"
```

Verify `createDeepAgent`, `LocalShellBackend`, `SubAgent` are exported.

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A
git commit -m "chore: verify DeepAgent integration builds and starts cleanly"
```

---

## Key Architectural Decisions

1. **`LocalShellBackend`** — Used instead of `StateBackend` because Malibu operates on a real filesystem (the user's project directory). `LocalShellBackend` provides `execute()` for shell commands and real file I/O. DeepAgent's built-in filesystem tools (`read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep`) will coexist with Malibu's custom tools (which have richer metadata, permissions, and TUI integration). Malibu's tools take precedence when names conflict.

2. **No `FilesystemMiddleware` tools used** — We pass Malibu's own tools (bash, read, edit, write, grep, glob, etc.) which have permission integration, metadata side-channels, and TUI rendering. DeepAgent's built-in filesystem tools would conflict. We may need to configure `createFilesystemMiddleware({ systemPrompt: null })` or filter out built-in tools to prevent duplicates.

3. **Sub-agent dispatch via `task` tool** — DeepAgent automatically creates a `task` tool that delegates to sub-agents. When the LLM wants to use `explore` or `general`, it calls the `task` tool with the sub-agent name. This replaces the manual `@agent` dispatch in `prompt.ts`.

4. **`SummarizationMiddleware`** — DeepAgent includes this automatically. It replaces the custom `CompactionMiddleware` for context overflow handling. The middleware auto-computes trigger thresholds based on the model's context window.

5. **Skills** — Skill paths from `.agents/skills/` are passed to `createDeepAgent({ skills: [...] })`. DeepAgent's `SkillsMiddleware` loads SKILL.md files and makes them available to the agent.

6. **Streaming compatibility** — `DeepAgent` extends `ReactAgent`, so `agent.stream(input, { streamMode: "messages" })` produces the same `AIMessageChunk` / `ToolMessage` events. The existing `streamAgent()` loop works unchanged.

7. **`interruptOn`** — Maps Malibu's `"ask"` permission rules to DeepAgent's HITL interrupt mechanism. When a tool with `interruptOn: true` is called, the agent pauses and emits a `GraphInterrupt`, which the existing `harness-processor.ts` handles.

## Risk Mitigation

- **Built-in tool conflicts**: DeepAgent adds `read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep`, `task` tools automatically. Malibu has `read`, `edit`, `write`, `bash`, `grep`, `glob`, `list` tools. Names don't conflict exactly (e.g. `read` vs `read_file`), but descriptions may confuse the LLM. Monitor for tool selection issues.

- **Middleware ordering**: DeepAgent applies middleware in a fixed order. Custom middleware (for permissions) is appended after built-in middleware. Verify permission checks happen before tool execution.

- **Token usage**: DeepAgent's `SummarizationMiddleware` may handle token counting differently than Malibu's `Session.getUsage()`. The `streamAgent()` loop still extracts `usage_metadata` from `AIMessageChunk`, so cost tracking should work.

- **Checkpointer compatibility**: Our `SqliteCheckpointer` implements `BaseCheckpointSaver` from `@langchain/langgraph-checkpoint`. `createDeepAgent` accepts `BaseCheckpointSaver | boolean`. Should be directly compatible.
