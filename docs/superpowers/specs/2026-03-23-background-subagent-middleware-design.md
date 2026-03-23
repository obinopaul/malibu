# Background Subagent Middleware — Design Spec

## Problem

The current sync subagent middleware (`createSubAgentMiddleware`) blocks the parent agent while a subagent runs to completion. For long-running tasks, this means the agent cannot do other work, respond to the user, or launch parallel workstreams that complete independently.

The existing `createAsyncSubAgentMiddleware` solves this but requires a remote LangGraph server deployment — making it unsuitable for a distributable CLI tool where users don't have server infrastructure.

## Solution

An **in-process background subagent middleware** that uses JavaScript Promises (analogous to Python's `asyncio.create_task()`) to fire-and-forget subagent executions. The middleware provides tools for the agent to launch, monitor, wait for, and cancel background tasks. An optional orchestrator wraps the agent to automatically collect results when the agent finishes with pending tasks.

## Prior Art

| System | Pattern | Background? |
|--------|---------|-------------|
| Gemini CLI | `Promise.all()` batching of parallel tools | No — blocks until all complete |
| Qwen Code | Auto-parallelize Agent tool calls via `Promise.all()` | No — blocks until all complete |
| DeepAgents async_subagents.ts | Remote LangGraph server + SDK Client | Yes — but requires server |
| User's Python BackgroundSubagentMiddleware | `asyncio.create_task()` + registry + orchestrator | Yes — in-process, no server |

This design ports the Python pattern to TypeScript.

## Architecture

### File Structure

```
deepagentsjs/libs/deepagents/src/middleware/
├── background_subagents.ts       # Middleware + orchestrator + registry
├── background_subagents.test.ts  # Tests
```

### Components

#### 1. BackgroundTaskRegistry

In-memory registry tracking background Promises and their metadata. Stored in a closure within the middleware — not serializable, but task metadata is persisted in LangGraph state.

```typescript
interface PromiseWrapper<T = Record<string, unknown>> {
  promise: Promise<T>;
  status: "pending" | "fulfilled" | "rejected";
  result?: T;
  error?: Error;
  startTime: number;
}

class BackgroundTaskRegistry {
  private tasks: Map<string, PromiseWrapper> = new Map();
  private nextTaskNumber: number = 1;
  private taskIdToNumber: Map<string, number> = new Map();

  register(taskId: string, promise: Promise<any>): number;
  get(taskId: string): PromiseWrapper | undefined;
  getByNumber(taskNumber: number): { taskId: string; wrapper: PromiseWrapper } | undefined;
  waitFor(taskId: string, timeoutMs?: number): Promise<any>;
  waitForAll(timeoutMs?: number): Promise<Map<string, any>>;
  cancel(taskId: string): boolean;
  getPendingCount(): number;
  getAllTasks(): Map<string, PromiseWrapper>;
  clear(): void;
}
```

**Promise status tracking:** JavaScript Promises don't expose `.status`. We attach `.then()/.catch()` callbacks at registration time to update the wrapper's `status`, `result`, and `error` fields synchronously.

**Task-N display IDs:** Sequential integer IDs (Task-1, Task-2, ...) for easy user reference. Mapped bidirectionally to UUIDs.

#### 2. State Schema

Persists task metadata in LangGraph state (survives context compaction). Mirrors the async_subagents.ts pattern.

```typescript
type BackgroundTaskStatus = "running" | "success" | "error" | "cancelled" | "timeout";

interface BackgroundTaskRecord {
  taskId: string;
  taskNumber: number;
  agentName: string;
  description: string;
  status: BackgroundTaskStatus;
  createdAt: string;
  completedAt?: string;
  result?: string;
  error?: string;
}

const BackgroundTaskStateSchema = new StateSchema({
  backgroundTasks: new ReducedValue(
    z.record(z.string(), BackgroundTaskRecordSchema).default(() => ({})),
    { reducer: backgroundTasksReducer },  // Shallow merge, same as async_subagents
  ),
});
```

#### 3. Tools

**`background_task`** — Launch a subagent in the background, return immediately with Task-N ID.

| Parameter | Type | Description |
|-----------|------|-------------|
| `description` | string | Task description (becomes HumanMessage to subagent) |
| `subagent_type` | string | Which subagent to use |

Flow:
1. Validate `subagent_type` exists
2. Filter parent state (same as sync middleware)
3. Create Promise via `subagent.invoke(state, config)` — **do NOT await**
4. Register Promise in BackgroundTaskRegistry
5. Return `Command` with ToolMessage ("Background task deployed: Task-N") + state update

**`task_progress`** — Non-blocking status check.

| Parameter | Type | Description |
|-----------|------|-------------|
| `task_number` | number | The Task-N number to check |

Flow:
1. Look up PromiseWrapper by task number
2. Read `wrapper.status` (updated synchronously by callbacks)
3. If fulfilled, extract result summary
4. Return `Command` with status update

**`wait`** — Block until task(s) complete.

| Parameter | Type | Description |
|-----------|------|-------------|
| `task_number` | number (optional) | Specific task to wait for. Omit to wait for all. |
| `timeout_ms` | number (optional) | Timeout in ms. Default 120000 (2 min). |

Flow:
1. If task_number provided: `Promise.race([registry.waitFor(taskId), timeoutPromise])`
2. If omitted: `Promise.race([registry.waitForAll(), timeoutPromise])`
3. Return `Command` with results + state updates for all completed tasks

**`cancel_background_task`** — Cancel a running task.

| Parameter | Type | Description |
|-----------|------|-------------|
| `task_number` | number | The Task-N number to cancel |

Flow:
1. Look up task, mark as cancelled in registry and state
2. Note: JS Promises are not cancellable natively. We mark status as "cancelled" and ignore the result when it resolves. If the subagent supports AbortSignal, we can signal it.

#### 4. System Prompt

Injected via `wrapModelCall` (same pattern as sync/async middleware):

```
## Background subagents (in-process)

You can launch subagents in the background using `background_task`.
They execute as background tasks while you continue working.

### Tools:
- `background_task`: Launch a subagent in the background. Returns Task-N ID immediately.
- `task_progress`: Check status of a background task without blocking.
- `wait`: Wait for a specific task or all tasks to complete (with timeout).
- `cancel_background_task`: Cancel a running background task.

### Workflow:
1. Launch tasks with `background_task` — you get a Task-N ID immediately
2. Continue with other work while tasks run in background
3. Check progress with `task_progress` when needed
4. Use `wait` when you need results before continuing
5. Cancel unnecessary tasks with `cancel_background_task`

### Rules:
- After launching, continue with other work. Do NOT immediately wait or check.
- You can launch multiple background tasks — they run concurrently.
- Use `wait()` (no args) to wait for ALL pending tasks at once.
- Task results in conversation history may be stale — always use tools for current status.
```

#### 5. createBackgroundSubAgentMiddleware()

Main entry point. Follows `createSubAgentMiddleware` pattern exactly.

```typescript
interface BackgroundSubAgentMiddlewareOptions {
  defaultModel: LanguageModelLike | string;
  defaultTools?: StructuredTool[];
  defaultMiddleware?: AgentMiddleware[] | null;
  generalPurposeMiddleware?: AgentMiddleware[] | null;
  defaultInterruptOn?: Record<string, boolean | InterruptOnConfig> | null;
  subagents?: (SubAgent | CompiledSubAgent)[];
  generalPurposeAgent?: boolean;
  systemPrompt?: string | null;
  timeout?: number;  // Default wait timeout (ms), default 120000
}

function createBackgroundSubAgentMiddleware(
  options: BackgroundSubAgentMiddlewareOptions
): AgentMiddleware;
```

Internally:
1. Calls `getSubagents()` (reuse from subagents.ts) to build subagent graphs
2. Creates `BackgroundTaskRegistry` instance (lives in closure)
3. Creates 4 tools (all close over registry + subagentGraphs)
4. Returns `createMiddleware({ name, tools, stateSchema, wrapModelCall })`

#### 6. BackgroundSubAgentOrchestrator

Optional wrapper that implements the "waiting room" pattern. Wraps any agent's execution to auto-collect background results.

```typescript
class BackgroundSubAgentOrchestrator {
  constructor(
    private registry: BackgroundTaskRegistry,
    private timeout: number = 120000,
  ) {}

  /**
   * Wrap an agent stream to implement the waiting room.
   * After the agent's stream ends, if there are pending background tasks:
   * 1. Wait for all pending tasks (with timeout)
   * 2. Inject results as messages
   * 3. Re-invoke the agent for synthesis
   */
  async *wrapStream(
    agent: Runnable,
    input: any,
    config: any,
  ): AsyncGenerator<any>;
}
```

The orchestrator is exported separately and used opt-in by the harness.

## Integration into Malibu

In `packages/opencode/src/agent/create-agent.ts`:

```typescript
import { createBackgroundSubAgentMiddleware } from "deepagents";

// Add to middleware array alongside existing subagent middleware
const builtInMiddleware = [
  todoListMiddleware(),
  createSubAgentMiddleware({ ... }),           // Sync task tool (existing)
  createBackgroundSubAgentMiddleware({         // NEW: Background task tool
    defaultModel: model,
    defaultTools: tools,
    subagents,
    generalPurposeAgent: true,
  }),
  createSummarizationMiddleware({ ... }),
  createPatchToolCallsMiddleware(),
];
```

Both sync `task` and async `background_task` tools coexist — the agent chooses based on whether it needs the result immediately or can continue working.

## Key Design Decisions

1. **Separate tool name (`background_task`)** — Coexists with sync `task` tool. Agent explicitly chooses blocking vs. background.
2. **Promise wrapper pattern** — Solves JS Promise status inspection limitation. Self-updating via `.then()/.catch()` callbacks.
3. **State + closure dual storage** — Task metadata in LangGraph state (serializable, survives compaction). Promise references in closure Map (not serializable, but needed for actual waiting).
4. **Orchestrator is opt-in** — Middleware works standalone with explicit `wait` calls. Orchestrator adds automatic result collection for users who want it.
5. **No AbortController by default** — JS Promises aren't cancellable. Cancel = mark as cancelled and ignore result. AbortSignal support can be added later if subagents accept it.
6. **Reuses `getSubagents()`** — Same subagent compilation logic as sync middleware. No duplication.
