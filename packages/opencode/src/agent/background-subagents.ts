/**
 * In-process background subagent middleware — standalone implementation.
 *
 * Spawns subagent executions as background Promises (no remote server required).
 * The main agent continues working while subagents execute concurrently.
 *
 * Provides four tools:
 * - `background_task`: Launch a subagent in the background, return immediately
 * - `task_progress`: Non-blocking status check
 * - `wait_background_task`: Block until task(s) complete (with timeout)
 * - `cancel_background_task`: Cancel a running task
 *
 * Optionally includes a {@link BackgroundSubAgentOrchestrator} that wraps agent
 * execution to auto-collect background results when the agent finishes.
 *
 * @module
 */

import { z } from "zod"
// @ts-expect-error — tsgo browser condition misses agent exports
import { createAgent, createMiddleware, tool, SystemMessage } from "langchain"
// @ts-expect-error — tsgo browser condition misses these types
import type { AgentMiddleware, ToolRuntime } from "langchain"
import type { StructuredTool } from "@langchain/core/tools"
import { ToolMessage, HumanMessage } from "@langchain/core/messages"
import type { BaseMessage } from "@langchain/core/messages"
import { Command, ReducedValue, StateSchema } from "@langchain/langgraph"
import type { Runnable, RunnableConfig } from "@langchain/core/runnables"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Possible statuses for a background task. */
export type BackgroundTaskStatus =
  | "running"
  | "success"
  | "error"
  | "cancelled"
  | "timeout"

/** Terminal statuses that will never change. */
export const TERMINAL_STATUSES = new Set<BackgroundTaskStatus>([
  "success",
  "error",
  "cancelled",
  "timeout",
])

/**
 * Serializable task metadata persisted in LangGraph state.
 * The actual Promise reference lives only in the in-memory registry.
 */
export interface BackgroundTaskRecord {
  taskId: string
  taskNumber: number
  agentName: string
  description: string
  status: BackgroundTaskStatus
  createdAt: string
  completedAt?: string
  result?: string
  error?: string
  toolCount?: number
  tokenUsage?: number
}

/** Shape of the background task state channel. */
type BackgroundTaskState = {
  backgroundTasks?: Record<string, BackgroundTaskRecord>
}

// ---------------------------------------------------------------------------
// State Schema
// ---------------------------------------------------------------------------

const BackgroundTaskRecordSchema = z.object({
  taskId: z.string(),
  taskNumber: z.number(),
  agentName: z.string(),
  description: z.string(),
  status: z.string(),
  createdAt: z.string(),
  completedAt: z.string().optional(),
  result: z.string().optional(),
  error: z.string().optional(),
  toolCount: z.number().optional(),
  tokenUsage: z.number().optional(),
})

/**
 * Reducer for the `backgroundTasks` state channel.
 * Merges task updates via shallow spread.
 */
export function backgroundTasksReducer(
  existing?: Record<string, BackgroundTaskRecord>,
  update?: Record<string, BackgroundTaskRecord>,
): Record<string, BackgroundTaskRecord> {
  return { ...(existing || {}), ...(update || {}) }
}

const BackgroundTaskStateSchema = new StateSchema({
  backgroundTasks: new ReducedValue(
    z.record(z.string(), BackgroundTaskRecordSchema).default(() => ({})) as any,
    {
      inputSchema: z.record(z.string(), BackgroundTaskRecordSchema).optional() as any,
      reducer: backgroundTasksReducer,
    },
  ),
})

// ---------------------------------------------------------------------------
// Promise Wrapper (solves JS Promise status inspection)
// ---------------------------------------------------------------------------

interface PromiseWrapper<T = Record<string, unknown>> {
  promise: Promise<T>
  status: "pending" | "fulfilled" | "rejected"
  result?: T
  error?: Error
  startTime: number
}

function wrapPromise<T>(promise: Promise<T>): PromiseWrapper<T> {
  const wrapper: PromiseWrapper<T> = {
    promise,
    status: "pending",
    startTime: Date.now(),
  }

  promise.then(
    (result) => {
      wrapper.status = "fulfilled"
      wrapper.result = result
    },
    (error) => {
      wrapper.status = "rejected"
      wrapper.error = error instanceof Error ? error : new Error(String(error))
    },
  )

  return wrapper
}

// ---------------------------------------------------------------------------
// Background Task Registry
// ---------------------------------------------------------------------------

/**
 * In-memory registry tracking background Promises and their metadata.
 * Lives in a closure within the middleware — not serializable.
 * Task metadata is separately persisted in LangGraph state.
 */
export class BackgroundTaskRegistry {
  private tasks = new Map<string, PromiseWrapper>()
  private nextTaskNumber = 1
  private numberToId = new Map<number, string>()
  private idToNumber = new Map<string, number>()

  /** Register a new background task. Returns the assigned task number. */
  register(taskId: string, promise: Promise<any>): number {
    const taskNumber = this.nextTaskNumber++
    const wrapper = wrapPromise(promise)
    this.tasks.set(taskId, wrapper)
    this.numberToId.set(taskNumber, taskId)
    this.idToNumber.set(taskId, taskNumber)
    return taskNumber
  }

  /** Get a task wrapper by ID. */
  get(taskId: string): PromiseWrapper | undefined {
    return this.tasks.get(taskId)
  }

  /** Get a task wrapper by sequential number. */
  getByNumber(taskNumber: number): { taskId: string; wrapper: PromiseWrapper } | undefined {
    const taskId = this.numberToId.get(taskNumber)
    if (!taskId) return undefined
    const wrapper = this.tasks.get(taskId)
    if (!wrapper) return undefined
    return { taskId, wrapper }
  }

  /** Get the task number for a task ID. */
  getNumber(taskId: string): number | undefined {
    return this.idToNumber.get(taskId)
  }

  /** Wait for a specific task with optional timeout. Throws on rejection or timeout. */
  async waitFor(taskId: string, timeoutMs = 120_000): Promise<any> {
    const wrapper = this.tasks.get(taskId)
    if (!wrapper) throw new Error(`No task found: ${taskId}`)

    if (wrapper.status === "fulfilled") return wrapper.result
    if (wrapper.status === "rejected") throw wrapper.error

    let timerId: ReturnType<typeof setTimeout>
    const timeoutPromise = new Promise<never>((_, reject) => {
      timerId = setTimeout(() => reject(new Error("TIMEOUT")), timeoutMs)
    })

    try {
      const result = await Promise.race([wrapper.promise, timeoutPromise])
      clearTimeout(timerId!)
      return result
    } catch (err) {
      clearTimeout(timerId!)
      throw err
    }
  }

  /** Wait for all pending tasks with optional timeout. */
  async waitForAll(timeoutMs = 120_000): Promise<Map<string, any>> {
    const results = new Map<string, any>()
    const pending: Array<{ taskId: string; wrapper: PromiseWrapper }> = []

    for (const [taskId, wrapper] of this.tasks) {
      if (wrapper.status === "pending") {
        pending.push({ taskId, wrapper })
      } else if (wrapper.status === "fulfilled") {
        results.set(taskId, wrapper.result)
      } else {
        results.set(taskId, { error: wrapper.error?.message })
      }
    }

    if (pending.length === 0) return results

    let timerId: ReturnType<typeof setTimeout>
    const timeoutPromise = new Promise<never>((_, reject) => {
      timerId = setTimeout(() => reject(new Error("TIMEOUT")), timeoutMs)
    })

    try {
      await Promise.race([
        Promise.allSettled(pending.map((p) => p.wrapper.promise)),
        timeoutPromise,
      ])
    } catch {
      // Timeout — collect what we have
    } finally {
      clearTimeout(timerId!)
    }

    for (const { taskId, wrapper } of pending) {
      if (wrapper.status === "fulfilled") {
        results.set(taskId, wrapper.result)
      } else if (wrapper.status === "rejected") {
        results.set(taskId, { error: wrapper.error?.message })
      } else {
        results.set(taskId, { error: "Timed out — task may still be running" })
      }
    }

    return results
  }

  /** Mark a task as cancelled. Returns true if cancelled, false if already done. */
  cancel(taskId: string): boolean {
    const wrapper = this.tasks.get(taskId)
    if (!wrapper || wrapper.status !== "pending") return false
    wrapper.status = "rejected"
    wrapper.error = new Error("Cancelled")
    return true
  }

  /** Count of tasks still pending. */
  get pendingCount(): number {
    let count = 0
    for (const wrapper of this.tasks.values()) {
      if (wrapper.status === "pending") count++
    }
    return count
  }

  /** Check if there are any pending tasks. */
  get hasPending(): boolean {
    for (const wrapper of this.tasks.values()) {
      if (wrapper.status === "pending") return true
    }
    return false
  }

  /** Get all tasks. */
  getAll(): Map<string, PromiseWrapper> {
    return new Map(this.tasks)
  }

  /** Store extracted metrics for a task. */
  private metrics = new Map<string, { toolCount: number; tokenUsage: number }>()

  setMetrics(taskId: string, metrics: { toolCount: number; tokenUsage: number }): void {
    this.metrics.set(taskId, metrics)
  }

  getMetrics(taskId: string): { toolCount: number; tokenUsage: number } | undefined {
    return this.metrics.get(taskId)
  }

  /** Clear all tasks and reset numbering. */
  clear(): void {
    this.tasks.clear()
    this.numberToId.clear()
    this.idToNumber.clear()
    this.metrics.clear()
    this.nextTaskNumber = 1
  }
}

// ---------------------------------------------------------------------------
// Helper: extract result content from subagent output
// ---------------------------------------------------------------------------

const INVALID_TOOL_MESSAGE_BLOCK_TYPES = [
  "tool_use",
  "thinking",
  "redacted_thinking",
]

export function extractResultContent(result: Record<string, unknown>): string {
  if (result.structuredResponse != null) {
    return JSON.stringify(result.structuredResponse)
  }

  const messages = result.messages as BaseMessage[] | undefined
  const lastMessage = messages?.[messages.length - 1]
  if (!lastMessage) return "Task completed"

  let content: any = lastMessage.content || "Task completed"
  if (Array.isArray(content)) {
    content = content.filter(
      (block: any) => !INVALID_TOOL_MESSAGE_BLOCK_TYPES.includes(block.type),
    )
    if (content.length === 0) return "Task completed"
    return content
      .map((block: any) => ("text" in block ? block.text : JSON.stringify(block)))
      .join("\n")
  }
  return content
}

/**
 * Extract tool count and token usage from subagent result messages.
 */
export function extractMetrics(result: Record<string, unknown>): {
  toolCount: number
  tokenUsage: number
} {
  const messages = result.messages as BaseMessage[] | undefined
  if (!messages) return { toolCount: 0, tokenUsage: 0 }

  let toolCount = 0
  let tokenUsage = 0

  for (const msg of messages) {
    if (msg instanceof ToolMessage) {
      toolCount++
    }
    const usage = (msg as any).usage_metadata
    if (usage?.total_tokens) {
      tokenUsage += usage.total_tokens
    }
  }

  return { toolCount, tokenUsage }
}

// ---------------------------------------------------------------------------
// State filtering
// ---------------------------------------------------------------------------

const EXCLUDED_STATE_KEYS = [
  "messages",
  "todos",
  "structuredResponse",
  "skillsMetadata",
  "memoryContents",
  "backgroundTasks",
] as const

/** @internal — exported for testing only */
export function filterStateForSubagent(
  state: Record<string, unknown>,
): Record<string, unknown> {
  const filtered: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(state)) {
    if (!EXCLUDED_STATE_KEYS.includes(key as never)) {
      filtered[key] = value
    }
  }
  return filtered
}

// ---------------------------------------------------------------------------
// Helpers: resolve existing record from state for non-destructive updates
// ---------------------------------------------------------------------------

/** @internal — exported for testing only */
export function toolCallIdFromRuntime(runtime: any): string {
  return runtime?.toolCall?.id ?? runtime?.toolCallId ?? ""
}

/** @internal — exported for testing only */
export function getExistingRecord(
  taskId: string,
  state: BackgroundTaskState,
): BackgroundTaskRecord | undefined {
  return state.backgroundTasks?.[taskId]
}

/** @internal — exported for testing only */
export function mergeRecord(
  existing: BackgroundTaskRecord | undefined,
  updates: Partial<BackgroundTaskRecord>,
): BackgroundTaskRecord {
  if (existing) {
    return { ...existing, ...updates }
  }
  return {
    taskId: updates.taskId ?? "",
    taskNumber: updates.taskNumber ?? 0,
    agentName: updates.agentName ?? "",
    description: updates.description ?? "",
    status: (updates.status as BackgroundTaskStatus) ?? "running",
    createdAt: updates.createdAt ?? new Date().toISOString(),
    ...updates,
  } as BackgroundTaskRecord
}

// ---------------------------------------------------------------------------
// System Prompt
// ---------------------------------------------------------------------------

export const BACKGROUND_TASK_SYSTEM_PROMPT = `## Background subagents (in-process)

You can launch subagents in the background using \`background_task\`.
They execute as background tasks while you continue working.

### Tools:
- \`background_task\`: Launch a subagent in the background. Returns a Task-N ID immediately.
- \`task_progress\`: Check status of a background task without blocking.
- \`wait_background_task\`: Wait for a specific task or all tasks to complete (with timeout).
- \`cancel_background_task\`: Cancel a running background task. Note: cancellation is best-effort — the underlying computation may continue briefly but the result will be ignored.

### Workflow:
1. **Launch** — Use \`background_task\` to start tasks. You get a Task-N ID immediately.
2. **Continue working** — Do other work while tasks run in the background.
3. **Check** (optional) — Use \`task_progress\` to peek at status without blocking.
4. **Wait** (when needed) — Use \`wait_background_task\` to block until results are ready.
5. **Cancel** (optional) — Use \`cancel_background_task\` to stop tasks you no longer need.

### Rules:
- After launching, continue with other work. Do NOT immediately wait or check.
- You can launch multiple background tasks — they run concurrently.
- Use \`wait_background_task()\` with no task_number to wait for ALL pending tasks at once.
- Task statuses in conversation history may be stale — always use tools for current status.
- Always show full Task-N IDs — never truncate.

### When to use background_task vs task:
- Use \`background_task\` when you have 2+ independent tasks to run concurrently.
- Use \`task\` (sync) ONLY for a single operation where you need the result before your next step.
- Use \`background_task\` for long-running research, analysis, or multi-step operations.
- Use \`task\` for quick single lookups or operations where blocking is fine.
- **CRITICAL: NEVER call multiple \`task\` tools in the same message — this will crash.** Use \`background_task\` for ALL parallel work.`

// ---------------------------------------------------------------------------
// Subagent Graph Builder
// ---------------------------------------------------------------------------

/** Description for an available background subagent. */
export interface BackgroundSubAgent {
  /** Name used in the background_task tool (e.g., "general-purpose", "explore"). */
  name: string
  /** Human-readable description shown to the LLM. */
  description: string
  /** System prompt for this subagent. */
  systemPrompt?: string
  /** Override model for this subagent (falls back to defaultModel). */
  model?: any
  /** Override tools for this subagent (falls back to defaultTools). */
  tools?: StructuredTool[]
  /** Override middleware for this subagent. */
  middleware?: readonly AgentMiddleware[]
}

/**
 * Build compiled subagent graphs from BackgroundSubAgent definitions.
 * Each subagent is a full ReactAgent built via langchain's createAgent.
 */
function buildSubagentGraphs(
  subagents: BackgroundSubAgent[],
  defaultModel: any,
  defaultTools: StructuredTool[],
  defaultMiddleware: AgentMiddleware[],
): { agents: Record<string, Runnable>; descriptions: string[] } {
  const agents: Record<string, Runnable> = {}
  const descriptions: string[] = []

  for (const sub of subagents) {
    const agent = createAgent({
      model: sub.model ?? defaultModel,
      tools: sub.tools ?? defaultTools,
      middleware: sub.middleware ?? defaultMiddleware,
      systemPrompt: sub.systemPrompt ?? `You are a ${sub.name} agent. Complete the task described in the user message.`,
      name: `bg-${sub.name}`,
    })
    agents[sub.name] = agent
    descriptions.push(`- **${sub.name}**: ${sub.description}`)
  }

  return { agents, descriptions }
}

// ---------------------------------------------------------------------------
// Tool Builders
// ---------------------------------------------------------------------------

function getBackgroundTaskToolDescription(descriptions: string[]): string {
  return `Launch a subagent in the background. The subagent executes asynchronously while the main agent continues working. Returns a Task-N ID immediately.

Available agent types:
${descriptions.join("\n")}

## Usage notes:
1. This tool launches a background task and returns immediately with a Task-N ID. Continue with other work.
2. Use \`task_progress\` to check status without blocking.
3. Use \`wait_background_task\` when you need the result before proceeding.
4. Multiple background tasks run concurrently — launch several at once for parallel work.
5. Each background task gets an isolated context window. Provide detailed instructions.`
}

/** @internal — exported for testing only */
export function buildBackgroundTaskTool(
  registry: BackgroundTaskRegistry,
  subagentGraphs: Record<string, Runnable>,
  descriptions: string[],
) {
  const description = getBackgroundTaskToolDescription(descriptions)

  return tool(
    async (
      input: { description: string; subagent_type: string },
      runtime: any,
    ): Promise<Command | string> => {
      const { description: taskDescription, subagent_type } = input

      if (!(subagent_type in subagentGraphs)) {
        const allowed = Object.keys(subagentGraphs)
          .map((k) => `\`${k}\``)
          .join(", ")
        return `Error: unknown agent type "${subagent_type}". Available: ${allowed}`
      }

      const subagent = subagentGraphs[subagent_type]

      // Get and filter parent state
      const currentState = (runtime?.state ?? {}) as Record<string, unknown>
      const subagentState = filterStateForSubagent(currentState)
      subagentState.messages = [new HumanMessage({ content: taskDescription })]

      const taskId = crypto.randomUUID()

      // Fire and forget — do NOT await.
      // Pass explicit empty callbacks to prevent the background subagent from
      // inheriting the parent graph's StreamMessagesHandler via AsyncLocalStorage.
      // Without this, the subagent's LLM tokens flow through the parent's stream
      // controller, causing ERR_INVALID_STATE after the parent stream closes.
      const resultPromise = subagent.invoke(subagentState, { callbacks: [] }) as Promise<
        Record<string, unknown>
      >

      // Capture metrics when the subagent completes
      resultPromise.then(
        (result) => {
          const metrics = extractMetrics(result)
          registry.setMetrics(taskId, metrics)
        },
        () => {
          // On error, no metrics to capture
        },
      )

      const taskNumber = registry.register(taskId, resultPromise)
      const toolCallId = toolCallIdFromRuntime(runtime)

      const now = new Date().toISOString()
      const truncatedDesc =
        taskDescription.length > 200
          ? taskDescription.slice(0, 200) + "..."
          : taskDescription

      const record: BackgroundTaskRecord = {
        taskId,
        taskNumber,
        agentName: subagent_type,
        description: truncatedDesc,
        status: "running",
        createdAt: now,
      }

      if (!toolCallId) {
        return `Background task deployed: **Task-${taskNumber}** (${subagent_type})\nTask: ${truncatedDesc}\nStatus: Running in background`
      }

      return new Command({
        update: {
          backgroundTasks: { [taskId]: record },
          messages: [
            new ToolMessage({
              content:
                `Background task deployed: **Task-${taskNumber}**\n` +
                `- Type: ${subagent_type}\n` +
                `- Task: ${truncatedDesc}\n` +
                `- Status: Running in background\n\n` +
                `Continue with other work. Use \`task_progress(task_number=${taskNumber})\` to check status, ` +
                `or \`wait_background_task(task_number=${taskNumber})\` to get results when ready.`,
              tool_call_id: toolCallId,
              name: "background_task",
            }),
          ],
        },
      })
    },
    {
      name: "background_task",
      description,
      schema: z.object({
        description: z
          .string()
          .describe("Detailed task description for the subagent"),
        subagent_type: z
          .string()
          .describe(
            `Name of the agent to use. Available: ${Object.keys(subagentGraphs).join(", ")}`,
          ),
      }),
    },
  )
}

/** @internal — exported for testing only */
export function buildTaskProgressTool(registry: BackgroundTaskRegistry) {
  return tool(
    async (
      input: { task_number: number },
      runtime: any,
    ): Promise<Command | string> => {
      const entry = registry.getByNumber(input.task_number)
      if (!entry) {
        return `No background task found: Task-${input.task_number}`
      }

      const { taskId, wrapper } = entry
      const toolCallId = toolCallIdFromRuntime(runtime)
      const existing = getExistingRecord(taskId, runtime?.state ?? {})

      let status: BackgroundTaskStatus
      let resultContent: string | undefined
      let errorContent: string | undefined

      if (wrapper.status === "fulfilled") {
        status = "success"
        const result = wrapper.result as Record<string, unknown>
        resultContent = extractResultContent(result)
      } else if (wrapper.status === "rejected") {
        status = wrapper.error?.message === "Cancelled" ? "cancelled" : "error"
        errorContent = wrapper.error?.message
      } else {
        status = "running"
      }

      const elapsed = Math.round((Date.now() - wrapper.startTime) / 1000)
      const metrics = registry.getMetrics(taskId)

      const updatedRecord = mergeRecord(existing, {
        taskId,
        taskNumber: input.task_number,
        status,
        ...(status !== "running" && { completedAt: new Date().toISOString() }),
        ...(resultContent && { result: resultContent }),
        ...(errorContent && { error: errorContent }),
        ...(metrics && { toolCount: metrics.toolCount, tokenUsage: metrics.tokenUsage }),
      })

      const message =
        status === "running"
          ? `Task-${input.task_number}: **running** (${elapsed}s elapsed)`
          : status === "success"
            ? `Task-${input.task_number}: **completed**\n\nResult:\n${resultContent}`
            : `Task-${input.task_number}: **${status}**${errorContent ? `\n\nError: ${errorContent}` : ""}`

      if (!toolCallId) return message

      return new Command({
        update: {
          backgroundTasks: { [taskId]: updatedRecord },
          messages: [
            new ToolMessage({
              content: message,
              tool_call_id: toolCallId,
              name: "task_progress",
            }),
          ],
        },
      })
    },
    {
      name: "task_progress",
      description:
        "Check the status of a background task without blocking. Returns current status and result if complete.",
      schema: z.object({
        task_number: z
          .number()
          .describe("The Task-N number to check (e.g., 1 for Task-1)"),
      }),
    },
  )
}

/** @internal — exported for testing only */
export function buildWaitTool(
  registry: BackgroundTaskRegistry,
  defaultTimeoutMs: number,
) {
  return tool(
    async (
      input: { task_number?: number; timeout_ms?: number },
      runtime: any,
    ): Promise<Command | string> => {
      const timeoutMs = input.timeout_ms ?? defaultTimeoutMs
      const toolCallId = toolCallIdFromRuntime(runtime)
      const state = (runtime?.state ?? {}) as BackgroundTaskState

      // Wait for specific task
      if (input.task_number != null) {
        const entry = registry.getByNumber(input.task_number)
        if (!entry) {
          return `No background task found: Task-${input.task_number}`
        }

        const { taskId, wrapper } = entry
        const existing = getExistingRecord(taskId, state)
        const metrics = registry.getMetrics(taskId)
        const metricsUpdate = metrics ? { toolCount: metrics.toolCount, tokenUsage: metrics.tokenUsage } : {}

        // Already done
        if (wrapper.status !== "pending") {
          const isSuccess = wrapper.status === "fulfilled"
          const resultContent = isSuccess
            ? extractResultContent(wrapper.result as Record<string, unknown>)
            : wrapper.error?.message ?? "Unknown error"

          const status: BackgroundTaskStatus = isSuccess
            ? "success"
            : wrapper.error?.message === "Cancelled"
              ? "cancelled"
              : "error"

          const message = isSuccess
            ? `Task-${input.task_number}: **completed**\n\nResult:\n${resultContent}`
            : `Task-${input.task_number}: **${status}**\n\n${resultContent}`

          const updatedRecord = mergeRecord(existing, {
            status,
            completedAt: new Date().toISOString(),
            ...(isSuccess ? { result: resultContent } : { error: resultContent }),
            ...metricsUpdate,
          })

          if (!toolCallId) return message

          return new Command({
            update: {
              backgroundTasks: { [taskId]: updatedRecord },
              messages: [
                new ToolMessage({
                  content: message,
                  tool_call_id: toolCallId,
                  name: "wait_background_task",
                }),
              ],
            },
          })
        }

        // Wait with timeout
        try {
          const result = await registry.waitFor(taskId, timeoutMs)
          const resultContent = extractResultContent(result)
          const message = `Task-${input.task_number}: **completed**\n\nResult:\n${resultContent}`

          const updatedRecord = mergeRecord(existing, {
            status: "success" as BackgroundTaskStatus,
            completedAt: new Date().toISOString(),
            result: resultContent,
            ...metricsUpdate,
          })

          if (!toolCallId) return message

          return new Command({
            update: {
              backgroundTasks: { [taskId]: updatedRecord },
              messages: [
                new ToolMessage({
                  content: message,
                  tool_call_id: toolCallId,
                  name: "wait_background_task",
                }),
              ],
            },
          })
        } catch (err) {
          const isTimeout = err instanceof Error && err.message === "TIMEOUT"
          const status: BackgroundTaskStatus = isTimeout ? "timeout" : "error"
          const errorMsg = isTimeout
            ? `Task-${input.task_number}: **timed out** after ${timeoutMs}ms — task may still be running`
            : `Task-${input.task_number}: **error** — ${err instanceof Error ? err.message : String(err)}`

          const updatedRecord = mergeRecord(existing, {
            status,
            ...(isTimeout ? {} : { completedAt: new Date().toISOString() }),
            error: errorMsg,
            ...metricsUpdate,
          })

          if (!toolCallId) return errorMsg

          return new Command({
            update: {
              backgroundTasks: { [taskId]: updatedRecord },
              messages: [
                new ToolMessage({
                  content: errorMsg,
                  tool_call_id: toolCallId,
                  name: "wait_background_task",
                }),
              ],
            },
          })
        }
      }

      // Wait for ALL pending tasks
      const allResults = await registry.waitForAll(timeoutMs)
      const stateUpdates: Record<string, BackgroundTaskRecord> = {}
      const lines: string[] = []

      for (const [taskId, result] of allResults) {
        const taskNumber = registry.getNumber(taskId)
        const wrapper = registry.get(taskId)
        if (!taskNumber || !wrapper) continue

        const existing = getExistingRecord(taskId, state)
        const isError =
          wrapper.status === "rejected" || (typeof result === "object" && result?.error)
        const resultStatus: BackgroundTaskStatus = isError ? "error" : "success"
        const content = isError
          ? result?.error ?? "Unknown error"
          : extractResultContent(result)

        lines.push(`### Task-${taskNumber}: **${resultStatus}**\n${content}`)

        const taskMetrics = registry.getMetrics(taskId)
        stateUpdates[taskId] = mergeRecord(existing, {
          status: resultStatus,
          completedAt: new Date().toISOString(),
          ...(isError ? { error: String(content) } : { result: String(content) }),
          ...(taskMetrics && { toolCount: taskMetrics.toolCount, tokenUsage: taskMetrics.tokenUsage }),
        })
      }

      const pendingCount = registry.pendingCount
      if (pendingCount > 0) {
        lines.push(`\n*${pendingCount} task(s) still running (timed out)*`)
      }

      const message = lines.length > 0
        ? lines.join("\n\n")
        : "No background tasks to wait for."

      // Append structured metadata for TUI rendering
      const taskSummaries = Object.values(stateUpdates).map((r) => ({
        taskId: r.taskId,
        taskNumber: r.taskNumber,
        agentName: r.agentName,
        description: r.description,
        status: r.status,
        toolCount: r.toolCount,
        tokenUsage: r.tokenUsage,
      }))
      const messageWithMeta = message + "\n\n<!-- BACKGROUND_TASKS:" + JSON.stringify(taskSummaries) + " -->"

      if (!toolCallId) return messageWithMeta

      return new Command({
        update: {
          backgroundTasks: stateUpdates,
          messages: [
            new ToolMessage({
              content: messageWithMeta,
              tool_call_id: toolCallId,
              name: "wait_background_task",
            }),
          ],
        },
      })
    },
    {
      name: "wait_background_task",
      description:
        "Wait for background task(s) to complete. If task_number is provided, waits for that specific task. " +
        "If omitted, waits for ALL pending background tasks. Returns results when done or on timeout.",
      schema: z.object({
        task_number: z
          .number()
          .optional()
          .describe(
            "The Task-N number to wait for. Omit to wait for all pending tasks.",
          ),
        timeout_ms: z
          .number()
          .optional()
          .describe(
            "Maximum time to wait in milliseconds. Default: 120000 (2 minutes).",
          ),
      }),
    },
  )
}

/** @internal — exported for testing only */
export function buildCancelTool(registry: BackgroundTaskRegistry) {
  return tool(
    async (
      input: { task_number: number },
      runtime: any,
    ): Promise<Command | string> => {
      const entry = registry.getByNumber(input.task_number)
      if (!entry) {
        return `No background task found: Task-${input.task_number}`
      }

      const { taskId, wrapper } = entry
      const toolCallId = toolCallIdFromRuntime(runtime)
      const existing = getExistingRecord(taskId, runtime?.state ?? {})

      if (wrapper.status !== "pending") {
        return `Task-${input.task_number} is already ${wrapper.status === "fulfilled" ? "completed" : "finished"} — cannot cancel.`
      }

      registry.cancel(taskId)

      const message = `Task-${input.task_number}: **cancelled**`

      const updatedRecord = mergeRecord(existing, {
        status: "cancelled" as BackgroundTaskStatus,
        completedAt: new Date().toISOString(),
      })

      if (!toolCallId) return message

      return new Command({
        update: {
          backgroundTasks: { [taskId]: updatedRecord },
          messages: [
            new ToolMessage({
              content: message,
              tool_call_id: toolCallId,
              name: "cancel_background_task",
            }),
          ],
        },
      })
    },
    {
      name: "cancel_background_task",
      description:
        "Cancel a running background task. The task will be marked as cancelled. " +
        "Note: cancellation is best-effort — the underlying computation may continue briefly but the result will be ignored.",
      schema: z.object({
        task_number: z
          .number()
          .describe("The Task-N number to cancel (e.g., 1 for Task-1)"),
      }),
    },
  )
}

// ---------------------------------------------------------------------------
// Middleware Options & Factory
// ---------------------------------------------------------------------------

/** Options for creating background subagent middleware. */
export interface BackgroundSubAgentMiddlewareOptions {
  /** The model to use for background subagents. */
  defaultModel: any
  /** The tools available to background subagents. */
  defaultTools?: StructuredTool[]
  /** Default middleware for background subagents. */
  defaultMiddleware?: AgentMiddleware[]
  /** Background subagent definitions. If empty and generalPurposeAgent is true, a default is created. */
  subagents?: BackgroundSubAgent[]
  /** Whether to include a general-purpose agent. Default: true. */
  generalPurposeAgent?: boolean
  /** System prompt override. Set to null to disable. */
  systemPrompt?: string | null
  /** Default wait timeout in milliseconds. Default: 120000. */
  timeout?: number
}

/**
 * Create background subagent middleware.
 *
 * Provides four tools for launching subagents in the background (in-process,
 * no remote server required) and monitoring their progress.
 *
 * @example
 * ```typescript
 * const { middleware, registry } = createBackgroundSubAgentMiddleware({
 *   defaultModel: model,
 *   defaultTools: tools,
 *   generalPurposeAgent: true,
 * })
 * ```
 */
export function createBackgroundSubAgentMiddleware(
  options: BackgroundSubAgentMiddlewareOptions,
): { middleware: ReturnType<typeof createMiddleware>; registry: BackgroundTaskRegistry } {
  const {
    defaultModel,
    defaultTools = [],
    defaultMiddleware = [],
    subagents = [],
    systemPrompt = BACKGROUND_TASK_SYSTEM_PROMPT,
    generalPurposeAgent = true,
    timeout = 120_000,
  } = options

  // Build subagent definitions
  const allSubagents = [...subagents]
  if (generalPurposeAgent && !allSubagents.some((s) => s.name === "general-purpose")) {
    allSubagents.push({
      name: "general-purpose",
      description:
        "General-purpose agent for researching complex questions and executing multi-step tasks.",
      systemPrompt:
        "You are a general-purpose agent. Execute complex, multi-step tasks using the available tools. Be thorough and provide detailed results.",
    })
  }

  if (allSubagents.length === 0) {
    throw new Error(
      "createBackgroundSubAgentMiddleware: no subagents configured. " +
        "Set generalPurposeAgent: true or provide subagents.",
    )
  }

  // Build compiled subagent graphs
  const { agents: subagentGraphs, descriptions } = buildSubagentGraphs(
    allSubagents,
    defaultModel,
    defaultTools,
    defaultMiddleware,
  )

  // Create registry (lives in closure)
  const registry = new BackgroundTaskRegistry()

  // Build tools
  const backgroundTaskTool = buildBackgroundTaskTool(registry, subagentGraphs, descriptions)
  const taskProgressTool = buildTaskProgressTool(registry)
  const waitTool = buildWaitTool(registry, timeout)
  const cancelTool = buildCancelTool(registry)

  const middleware = createMiddleware({
    name: "backgroundSubAgentMiddleware",
    tools: [backgroundTaskTool, taskProgressTool, waitTool, cancelTool],
    stateSchema: BackgroundTaskStateSchema,
    wrapModelCall: async (request: any, handler: any) => {
      if (systemPrompt !== null) {
        return handler({
          ...request,
          systemMessage: request.systemMessage.concat(
            new SystemMessage({ content: systemPrompt }),
          ),
        })
      }
      return handler(request)
    },
  })

  return { middleware, registry }
}

// ---------------------------------------------------------------------------
// Background SubAgent Orchestrator (opt-in waiting room)
// ---------------------------------------------------------------------------

/**
 * Orchestrator that wraps agent execution to auto-collect background task
 * results when the agent finishes with pending tasks.
 *
 * Implements the "waiting room" pattern:
 * 1. Agent runs normally
 * 2. When the agent finishes, check for pending background tasks
 * 3. Wait for all pending tasks (with timeout)
 * 4. Inject results as HumanMessages
 * 5. Re-invoke the agent for synthesis
 *
 * @example
 * ```typescript
 * const { middleware, registry } = createBackgroundSubAgentMiddleware({ ... })
 * const orchestrator = new BackgroundSubAgentOrchestrator(registry)
 * const result = await orchestrator.invoke(agent, input, config)
 * ```
 */
export class BackgroundSubAgentOrchestrator {
  constructor(
    private registry: BackgroundTaskRegistry,
    private timeout: number = 120_000,
    private maxReinvocations: number = 3,
  ) {}

  async invoke(
    agent: Runnable,
    input: Record<string, unknown>,
    config?: RunnableConfig,
  ): Promise<Record<string, unknown>> {
    let result = (await agent.invoke(input, config)) as Record<string, unknown>
    let reinvocations = 0

    while (
      this.registry.hasPending &&
      reinvocations < this.maxReinvocations
    ) {
      reinvocations++

      const taskResults = await this.registry.waitForAll(this.timeout)

      const resultLines: string[] = [
        "## Background Task Results\n",
        "The following background tasks have completed:\n",
      ]

      for (const [taskId, taskResult] of taskResults) {
        const taskNumber = this.registry.getNumber(taskId)
        const wrapper = this.registry.get(taskId)
        if (!taskNumber || !wrapper) continue

        const isError =
          wrapper.status === "rejected" ||
          (typeof taskResult === "object" && taskResult?.error)

        if (isError) {
          const errorMsg = taskResult?.error ?? wrapper.error?.message ?? "Unknown error"
          resultLines.push(`### Task-${taskNumber}: **error**\n${errorMsg}\n`)
        } else {
          const content = extractResultContent(taskResult)
          resultLines.push(`### Task-${taskNumber}: **completed**\n${content}\n`)
        }
      }

      const pendingCount = this.registry.pendingCount
      if (pendingCount > 0) {
        resultLines.push(
          `\n*${pendingCount} task(s) still pending after timeout*`,
        )
      }

      resultLines.push(
        "\nPlease synthesize the above background task results and provide a final response to the user.",
      )

      const messages = (result.messages as BaseMessage[]) || []
      const nextInput = {
        ...result,
        messages: [
          ...messages,
          new HumanMessage({ content: resultLines.join("\n") }),
        ],
      }

      result = (await agent.invoke(nextInput, config)) as Record<string, unknown>
    }

    return result
  }
}
