/**
 * Sub-Agent Parallel Execution Diagnostic Tests
 *
 * Investigates why the agent crashes when calling the task tool in parallel.
 * Tests both the sync SubAgentMiddleware (deepagents) and the background
 * SubAgentMiddleware (custom in-process).
 *
 * Writes full diagnostic output to test/agent/output/task-tool-diagnostic-output.md
 *
 * Uses bun:test. Run with:
 *   cd packages/opencode && bun test test/agent/subagent-parallel.test.ts --timeout 120000
 */
import { describe, expect, test, beforeEach, afterEach, afterAll, mock } from "bun:test"
import fs from "fs/promises"
import path from "path"
import os from "os"
import { Command } from "@langchain/langgraph"
import { AIMessage, AIMessageChunk, HumanMessage, ToolMessage, BaseMessage } from "@langchain/core/messages"
import { ChatGenerationChunk, type ChatResult } from "@langchain/core/outputs"
import { BaseChatModel, type BaseChatModelParams } from "@langchain/core/language_models/chat_models"
import type { CallbackManagerForLLMRun } from "@langchain/core/callbacks/manager"
import {
  createSubAgentMiddleware,
  createPatchToolCallsMiddleware,
  createSummarizationMiddleware,
  LocalShellBackend,
} from "deepagents"
import type { SubAgent } from "deepagents"

/**
 * A fake chat model that cycles through pre-defined AIMessage objects.
 * Supports tool_calls and streaming, with a shared counter so
 * bindTools copies cycle in lockstep with the original.
 */
class CyclingFakeModel extends BaseChatModel {
  private responses: AIMessage[]
  /** Shared counter so bindTools copies cycle in lockstep with the original */
  private counter: { value: number }

  constructor(responses: AIMessage[], params?: BaseChatModelParams, counter?: { value: number }) {
    super(params ?? {})
    this.responses = responses
    this.counter = counter ?? { value: 0 }
  }

  _llmType() { return "cycling-fake" }
  _combineLLMOutput() { return [] }

  /** Required by langchain's createAgent — tools are ignored since we return pre-defined responses */
  bindTools(tools: any[]): any {
    return new CyclingFakeModel(this.responses, {}, this.counter)
  }

  async _generate(
    _messages: BaseMessage[],
    _options?: this["ParsedCallOptions"],
    _runManager?: CallbackManagerForLLMRun,
  ): Promise<ChatResult> {
    const msg = this.responses[this.counter.value % this.responses.length]
    this.counter.value++
    return {
      generations: [{ message: msg, text: typeof msg.content === "string" ? msg.content : "" }],
    }
  }

  async *_streamResponseChunks(
    _messages: BaseMessage[],
    _options: this["ParsedCallOptions"],
    _runManager?: CallbackManagerForLLMRun,
  ): AsyncGenerator<ChatGenerationChunk> {
    const msg = this.responses[this.counter.value % this.responses.length]
    this.counter.value++

    // Emit tool calls if present
    if (msg.tool_calls && msg.tool_calls.length > 0) {
      const chunk = new AIMessageChunk({
        content: typeof msg.content === "string" ? msg.content : "",
        tool_calls: msg.tool_calls,
      })
      yield new ChatGenerationChunk({
        message: chunk,
        text: "",
      })
      return
    }

    // Stream text char-by-char
    const text = typeof msg.content === "string" ? msg.content : ""
    for (const ch of text) {
      yield new ChatGenerationChunk({
        message: new AIMessageChunk({ content: ch }),
        text: ch,
      })
    }
  }
}

import {
  BackgroundTaskRegistry,
  backgroundTasksReducer,
  buildBackgroundTaskTool,
  buildTaskProgressTool,
  buildWaitTool,
  buildCancelTool,
  extractResultContent,
  type BackgroundTaskRecord,
  type BackgroundTaskStatus,
} from "../../src/agent/background-subagents"
import { createMalibuAgent } from "../../src/agent/create-agent"
import { SqliteCheckpointer } from "../../src/agent/checkpointer"
import { Bus } from "../../src/bus"
import { Harness } from "../../src/agent/harness"
import { tmpdir } from "../fixture/fixture"
import { Instance } from "../../src/project/instance"
import { canonTool, sameTool } from "../../src/tool/alias"

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

type BackgroundTaskState = {
  backgroundTasks?: Record<string, BackgroundTaskRecord>
}

function makeRecord(
  overrides: Partial<BackgroundTaskRecord> = {},
): BackgroundTaskRecord {
  return {
    taskId: "task-uuid-1",
    taskNumber: 1,
    agentName: "general-purpose",
    description: "Test task",
    status: "running" as BackgroundTaskStatus,
    createdAt: "2024-01-01T00:00:00.000Z",
    ...overrides,
  }
}

function makeRuntime(
  toolCallId: string,
  state: BackgroundTaskState = {},
): any {
  return {
    toolCall: { id: toolCallId },
    toolCallId,
    state,
  }
}

function makeMockSubagent(result: Record<string, unknown> = { messages: [{ content: "Subagent done" }] }) {
  return {
    invoke: mock(() => Promise.resolve(result)),
  } as any
}

/** Create a CyclingFakeModel that returns immediate text */
function makeFakeModel(text: string = "Done.") {
  return new CyclingFakeModel([new AIMessage({ content: text })])
}

/** Delay helper */
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

// ---------------------------------------------------------------------------
// Diagnostic output collector
// ---------------------------------------------------------------------------

interface DiagnosticEntry {
  elapsed: number
  type: string
  content?: string
  toolCalls?: any[]
  toolCallChunks?: any[]
  toolCallId?: string
  toolName?: string
  error?: { message: string; stack?: string }
}

const allDiagnostics: Array<{
  testName: string
  entries: DiagnosticEntry[]
  crashed: boolean
  crashError?: { message: string; stack?: string }
  startTime: number
}> = []

function startDiagnostic(testName: string) {
  const entries: DiagnosticEntry[] = []
  const startTime = performance.now()

  const diag = { testName, entries, crashed: false, startTime }
  allDiagnostics.push(diag)

  return {
    log(entry: Omit<DiagnosticEntry, "elapsed">) {
      const elapsed = Math.round(performance.now() - startTime)
      entries.push({ elapsed, ...entry })
    },
    markCrash(error: Error) {
      diag.crashed = true
      diag.crashError = { message: error.message, stack: error.stack }
    },
    entries,
  }
}

async function writeDiagnosticReport() {
  const outputPath = path.join(import.meta.dir, "output", "task-tool-diagnostic-output.md")
  const lines: string[] = []

  lines.push("# Task Tool Parallel Execution Diagnostic Report")
  lines.push(`Generated: ${new Date().toISOString()}`)
  lines.push("")

  for (const diag of allDiagnostics) {
    const status = diag.crashed ? "**CRASHED**" : "**PASS**"
    lines.push(`## Test: ${diag.testName}`)
    lines.push(`Status: ${status}`)
    lines.push("")

    if (diag.entries.length > 0) {
      lines.push("### Event Timeline")
      lines.push("")
      lines.push("| T+ms | Type | Details |")
      lines.push("|------|------|---------|")

      for (const entry of diag.entries) {
        const time = String(entry.elapsed).padStart(6)
        const type = entry.type
        let details = ""

        if (entry.error) {
          details = `ERROR: ${entry.error.message.slice(0, 100)}`
        } else if (entry.toolCallId) {
          details = `id=${entry.toolCallId} name=${entry.toolName ?? "?"}`
          if (entry.content) details += ` content=${entry.content.slice(0, 80)}`
        } else if (entry.content) {
          details = entry.content.slice(0, 100)
        } else if (entry.toolCalls) {
          details = entry.toolCalls.map((tc: any) => `${tc.name}(${tc.id})`).join(", ")
        }

        details = details.replace(/\|/g, "\\|").replace(/\n/g, " ")
        lines.push(`| ${time} | ${type} | ${details} |`)
      }
      lines.push("")
    }

    if (diag.crashed && diag.crashError) {
      lines.push("### Crash Details")
      lines.push("")
      lines.push("```")
      lines.push(`Error: ${diag.crashError.message}`)
      lines.push("")
      lines.push("Stack trace:")
      lines.push(diag.crashError.stack ?? "No stack trace")
      lines.push("```")
      lines.push("")
    }

    // Compute summary stats for this test
    const errors = diag.entries.filter((e) => e.type.includes("error") || e.type.includes("crash"))
    const toolMessages = diag.entries.filter((e) => e.type === "ToolMessage")
    const toolCalls = diag.entries.filter((e) => e.type.includes("tool_call"))

    lines.push("### Summary")
    lines.push(`- Events: ${diag.entries.length}`)
    lines.push(`- Tool calls detected: ${toolCalls.length}`)
    lines.push(`- Tool messages received: ${toolMessages.length}`)
    lines.push(`- Errors: ${errors.length}`)
    lines.push(`- Orphaned tool calls: ${toolCalls.length - toolMessages.length}`)
    lines.push("")
    lines.push("---")
    lines.push("")
  }

  // Overall summary
  const passed = allDiagnostics.filter((d) => !d.crashed).length
  const failed = allDiagnostics.filter((d) => d.crashed).length
  lines.push("## Overall Summary")
  lines.push(`- Total tests: ${allDiagnostics.length}`)
  lines.push(`- Passed: ${passed}`)
  lines.push(`- Crashed: ${failed}`)
  lines.push("")

  await fs.mkdir(path.dirname(outputPath), { recursive: true })
  await fs.writeFile(outputPath, lines.join("\n"), "utf-8")
  console.log(`\nDiagnostic report written to: ${outputPath}`)
}

afterEach(async () => {
  await Instance.disposeAll()
})

afterAll(async () => {
  await writeDiagnosticReport()
})

// ===========================================================================
// Section 1: BackgroundTaskRegistry Parallel Isolation
// ===========================================================================

describe("1. BackgroundTaskRegistry — parallel isolation", () => {
  let registry: BackgroundTaskRegistry

  beforeEach(() => {
    registry = new BackgroundTaskRegistry()
  })

  test("10 parallel tasks with staggered delays all resolve via waitForAll", async () => {
    const resolvers: Array<(v: any) => void> = []
    const promises: Promise<any>[] = []

    for (let i = 0; i < 10; i++) {
      const p = new Promise((resolve) => {
        resolvers.push(resolve)
      })
      promises.push(p)
      const num = registry.register(`task-${i}`, p)
      expect(num).toBe(i + 1)
    }

    // Resolve in staggered order
    for (let i = 9; i >= 0; i--) {
      resolvers[i]({ messages: [{ content: `Result ${i}` }] })
      await delay(5) // Small stagger
    }

    const results = await registry.waitForAll(5000)
    expect(results.size).toBe(10)

    for (let i = 0; i < 10; i++) {
      const result = results.get(`task-${i}`)
      expect(result).toBeDefined()
      expect(result.messages[0].content).toBe(`Result ${i}`)
    }
    console.log("  [PASS] 10 parallel tasks all resolved correctly")
  })

  test("concurrent cancel + waitFor race condition", async () => {
    let resolve1: (v: any) => void
    let resolve3: (v: any) => void

    const p1 = new Promise((r) => { resolve1 = r })
    const p2 = new Promise(() => {}) // Never resolves
    const p3 = new Promise((r) => { resolve3 = r })

    registry.register("id-1", p1)
    registry.register("id-2", p2)
    registry.register("id-3", p3)

    // Cancel task 2 while tasks 1 and 3 are pending
    const cancelled = registry.cancel("id-2")
    expect(cancelled).toBe(true)

    // Resolve tasks 1 and 3
    resolve1!({ messages: [{ content: "Task 1 done" }] })
    resolve3!({ messages: [{ content: "Task 3 done" }] })

    // Wait for task 1 — should succeed
    const result1 = await registry.waitFor("id-1", 2000)
    expect(result1.messages[0].content).toBe("Task 1 done")

    // Wait for task 2 — should throw "Cancelled"
    const wrapper2 = registry.get("id-2")
    expect(wrapper2!.status).toBe("rejected")
    expect(wrapper2!.error!.message).toBe("Cancelled")

    // Wait for task 3 — should succeed
    const result3 = await registry.waitFor("id-3", 2000)
    expect(result3.messages[0].content).toBe("Task 3 done")

    console.log("  [PASS] Cancel + waitFor race condition handled correctly")
  })

  test("sequential task number assignment is deterministic", () => {
    const numbers: number[] = []
    for (let i = 0; i < 20; i++) {
      numbers.push(registry.register(`task-${i}`, new Promise(() => {})))
    }
    expect(numbers).toEqual(Array.from({ length: 20 }, (_, i) => i + 1))
    console.log("  [PASS] Task numbers assigned sequentially 1-20")
  })
})

// ===========================================================================
// Section 2: Sync Task Tool (via full agent) — The Crash Tests
//
// NOTE: The task tool from SubAgentMiddleware uses getCurrentTaskInput()
// which REQUIRES a LangGraph graph context (pregel scratchpad).
// It CANNOT be invoked directly outside a graph.
// All tests here must use createMalibuAgent + agent.stream().
// ===========================================================================

describe("2. Sync SubAgentMiddleware — via full agent (graph context required)", () => {
  function buildTestAgent(opts: {
    parallelTaskCalls: Array<{ id: string; description: string; subagent_type: string }>
    checkpointer?: any
    tmpPath: string
  }) {
    const parentModel = new CyclingFakeModel([
      new AIMessage({
        content: "",
        tool_calls: opts.parallelTaskCalls.map((tc) => ({
          id: tc.id,
          name: "task",
          args: { description: tc.description, subagent_type: tc.subagent_type },
        })),
      }),
      new AIMessage({
        content: "All tasks completed. Here is the summary.",
      }),
    ])

    const subagentModel = new CyclingFakeModel([
      new AIMessage({ content: "Subagent exploration complete. Found relevant files." }),
    ])

    const explore: SubAgent = {
      name: "explore",
      description: "Fast agent for exploring codebases",
      systemPrompt: "You are an explore agent. Return findings.",
      model: subagentModel,
      tools: [],
    }

    const general: SubAgent = {
      name: "general",
      description: "General-purpose agent for multi-step tasks",
      systemPrompt: "You are a general agent. Complete the task.",
      model: subagentModel,
      tools: [],
    }

    const backend = new LocalShellBackend({ rootDir: opts.tmpPath })

    return createMalibuAgent({
      model: parentModel,
      tools: [],
      systemPrompt: "You are a helpful assistant. Use the task tool to delegate work.",
      checkpointer: opts.checkpointer ?? false,
      backend,
      subagents: [explore, general],
      name: "test-agent",
      isAnthropicModel: false,
    })
  }

  async function streamAndCapture(
    agent: ReturnType<typeof createMalibuAgent>,
    threadId: string,
    diag: ReturnType<typeof startDiagnostic>,
  ) {
    const stream = await agent.stream(
      { messages: [new HumanMessage("Explore the codebase in parallel.")] },
      {
        configurable: { thread_id: threadId },
        streamMode: "messages",
      },
    )

    let eventCount = 0
    let toolMsgCount = 0
    const toolCallIds: string[] = []
    const toolMessageIds: string[] = []

    for await (const event of stream) {
      eventCount++
      const [msg] = Array.isArray(event) ? event : [event]

      if (msg instanceof AIMessageChunk) {
        const tcChunks = msg.tool_call_chunks ?? []
        const tcs = msg.tool_calls ?? []
        const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)

        if (content && content !== "[]" && content !== '""') {
          diag.log({ type: "AIMessageChunk:text", content: content.slice(0, 200) })
        }

        for (const tc of tcChunks) {
          diag.log({
            type: "AIMessageChunk:tool_call_chunk",
            toolCallId: tc.id,
            toolName: tc.name,
            content: tc.args?.slice(0, 100),
          })
          if (tc.id) toolCallIds.push(tc.id)
        }

        for (const tc of tcs) {
          diag.log({
            type: "AIMessageChunk:tool_call",
            toolCallId: tc.id,
            toolName: tc.name,
            content: JSON.stringify(tc.args).slice(0, 100),
          })
          if (tc.id) toolCallIds.push(tc.id)
        }

        // Check for usage metadata
        const usage = (msg as any).usage_metadata
        if (usage) {
          diag.log({
            type: "AIMessageChunk:usage",
            content: JSON.stringify(usage),
          })
        }
      } else if (msg instanceof ToolMessage) {
        toolMsgCount++
        const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)
        const callId = (msg as any).tool_call_id ?? ""
        toolMessageIds.push(callId)
        diag.log({
          type: "ToolMessage",
          toolCallId: callId,
          toolName: msg.name,
          content: content.slice(0, 200),
        })
        console.log(`    ToolMessage: ${msg.name} (${callId}) — ${content.slice(0, 80)}`)
      } else if (msg instanceof AIMessage) {
        const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)
        diag.log({
          type: "AIMessage",
          content: content.slice(0, 200),
          toolCalls: msg.tool_calls?.map((tc) => ({ id: tc.id, name: tc.name })),
        })
        if (content) {
          console.log(`    AIMessage: ${content.slice(0, 100)}`)
        }
      } else {
        diag.log({
          type: `Other:${msg?.constructor?.name ?? "unknown"}`,
          content: JSON.stringify(msg).slice(0, 200),
        })
      }
    }

    diag.log({ type: "stream_end", content: `Total events: ${eventCount}` })

    // Report orphaned tool calls
    const uniqueToolCalls = [...new Set(toolCallIds)]
    const orphaned = uniqueToolCalls.filter((id) => !toolMessageIds.includes(id))

    if (orphaned.length > 0) {
      diag.log({
        type: "orphaned_tool_calls",
        content: `${orphaned.length} orphaned: ${orphaned.join(", ")}`,
      })
    }

    return { eventCount, toolMsgCount, toolCallIds: uniqueToolCalls, toolMessageIds, orphaned }
  }

  test("single task invocation — no checkpointer", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const diag = startDiagnostic("single task — no checkpointer")

        const agent = buildTestAgent({
          parallelTaskCalls: [
            { id: "call_1", description: "Explore the codebase", subagent_type: "explore" },
          ],
          tmpPath: tmp.path,
        })

        diag.log({ type: "agent_created" })
        console.log("  Agent created")

        try {
          const result = await streamAndCapture(agent, "test-single-" + Date.now(), diag)
          console.log(`  Stream: ${result.eventCount} events, ${result.toolMsgCount} tool messages`)
          console.log(`  Orphaned tool calls: ${result.orphaned.length}`)
        } catch (error: any) {
          diag.markCrash(error)
          console.error("  CRASH:", error.message)
          console.error("  Stack:", error.stack)
        }
      },
    })
  }, 30_000)

  test("2 parallel task calls — no checkpointer", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const diag = startDiagnostic("2 parallel tasks — no checkpointer")

        const agent = buildTestAgent({
          parallelTaskCalls: [
            { id: "call_explore_1", description: "Explore agent dir", subagent_type: "explore" },
            { id: "call_explore_2", description: "Explore test dir", subagent_type: "explore" },
          ],
          tmpPath: tmp.path,
        })

        diag.log({ type: "agent_created" })
        console.log("  Agent created")

        try {
          const result = await streamAndCapture(agent, "test-2par-" + Date.now(), diag)
          console.log(`  Stream: ${result.eventCount} events, ${result.toolMsgCount} tool messages`)
          console.log(`  Orphaned tool calls: ${result.orphaned.length}`)

          // Key observation: do we get ToolMessages back for both calls?
          if (result.toolMsgCount === 0) {
            console.log("  WARNING: 0 ToolMessages — subagent results came as AIMessageChunk text")
            console.log("  This means the harness will see these as orphaned tool calls")
          }
        } catch (error: any) {
          diag.markCrash(error)
          console.error("  CRASH:", error.message)
          console.error("  Stack:", error.stack)
        }
      },
    })
  }, 30_000)

  test("3 parallel task calls (same type) — no checkpointer", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const diag = startDiagnostic("3 parallel same-type tasks — no checkpointer")

        const agent = buildTestAgent({
          parallelTaskCalls: [
            { id: "call_1", description: "Explore area 1", subagent_type: "explore" },
            { id: "call_2", description: "Explore area 2", subagent_type: "explore" },
            { id: "call_3", description: "Explore area 3", subagent_type: "explore" },
          ],
          tmpPath: tmp.path,
        })

        diag.log({ type: "agent_created" })

        try {
          const result = await streamAndCapture(agent, "test-3par-" + Date.now(), diag)
          console.log(`  Stream: ${result.eventCount} events, ${result.toolMsgCount} tool messages`)
          console.log(`  Orphaned tool calls: ${result.orphaned.length}`)
        } catch (error: any) {
          diag.markCrash(error)
          console.error("  CRASH:", error.message)
          console.error("  Stack:", error.stack)
        }
      },
    })
  }, 30_000)

  test("2 parallel task calls — WITH SQLite checkpointer", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const diag = startDiagnostic("2 parallel tasks — SQLite checkpointer")

        const dbPath = path.join(os.tmpdir(), `malibu-test-cp-${Date.now()}.db`)
        let checkpointer: SqliteCheckpointer | undefined

        try {
          checkpointer = new SqliteCheckpointer(dbPath)
          diag.log({ type: "checkpointer_created", content: dbPath })
        } catch (error: any) {
          diag.log({ type: "checkpointer_error", error: { message: error.message, stack: error.stack } })
          console.error("  Failed to create checkpointer:", error.message)
          return
        }

        try {
          const agent = buildTestAgent({
            parallelTaskCalls: [
              { id: "call_cp_1", description: "Explore with checkpointer A", subagent_type: "explore" },
              { id: "call_cp_2", description: "Explore with checkpointer B", subagent_type: "explore" },
            ],
            checkpointer,
            tmpPath: tmp.path,
          })

          diag.log({ type: "agent_created" })
          console.log("  Agent created with SQLite checkpointer")

          const result = await streamAndCapture(agent, "test-cp-" + Date.now(), diag)
          console.log(`  Stream: ${result.eventCount} events, ${result.toolMsgCount} tool messages`)
          console.log(`  Orphaned tool calls: ${result.orphaned.length}`)
        } catch (error: any) {
          diag.markCrash(error)
          console.error("  CRASH with checkpointer:", error.message)
          console.error("  Name:", error.name)
          console.error("  Stack:", error.stack)

          // Check if it's a SQLite error
          if (error.message.includes("SQLITE") || error.message.includes("database")) {
            console.error("  >>> SQLite concurrency issue detected!")
          }
        } finally {
          // Cleanup
          try { await fs.unlink(dbPath).catch(() => {}) } catch {}
          try { await fs.unlink(dbPath + "-wal").catch(() => {}) } catch {}
          try { await fs.unlink(dbPath + "-shm").catch(() => {}) } catch {}
        }
      },
    })
  }, 60_000)

  test("3 parallel task calls — WITH SQLite checkpointer", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const diag = startDiagnostic("3 parallel tasks — SQLite checkpointer")

        const dbPath = path.join(os.tmpdir(), `malibu-test-cp3-${Date.now()}.db`)
        let checkpointer: SqliteCheckpointer | undefined

        try {
          checkpointer = new SqliteCheckpointer(dbPath)
        } catch (error: any) {
          diag.log({ type: "checkpointer_error", error: { message: error.message, stack: error.stack } })
          return
        }

        try {
          const agent = buildTestAgent({
            parallelTaskCalls: [
              { id: "call_3cp_1", description: "Explore area 1 (CP)", subagent_type: "explore" },
              { id: "call_3cp_2", description: "Explore area 2 (CP)", subagent_type: "explore" },
              { id: "call_3cp_3", description: "Explore area 3 (CP)", subagent_type: "explore" },
            ],
            checkpointer,
            tmpPath: tmp.path,
          })

          diag.log({ type: "agent_created" })
          console.log("  Agent created with SQLite checkpointer (3 parallel)")

          const result = await streamAndCapture(agent, "test-3cp-" + Date.now(), diag)
          console.log(`  Stream: ${result.eventCount} events, ${result.toolMsgCount} tool messages`)
          console.log(`  Orphaned tool calls: ${result.orphaned.length}`)
        } catch (error: any) {
          diag.markCrash(error)
          console.error("  CRASH with 3-parallel checkpointer:", error.message)
          console.error("  Stack:", error.stack)
        } finally {
          try { await fs.unlink(dbPath).catch(() => {}) } catch {}
          try { await fs.unlink(dbPath + "-wal").catch(() => {}) } catch {}
          try { await fs.unlink(dbPath + "-shm").catch(() => {}) } catch {}
        }
      },
    })
  }, 60_000)
})

// ===========================================================================
// Section 3: Background Task Tools — Parallel Launches
// ===========================================================================

describe("3. Background task tools — parallel launches", () => {
  let registry: BackgroundTaskRegistry

  beforeEach(() => {
    registry = new BackgroundTaskRegistry()
  })

  test("launch 3 background tasks in parallel — unique IDs", async () => {
    const subagentGraphs: Record<string, any> = {
      explore: makeMockSubagent({ messages: [{ content: "Explore result" }] }),
      general: makeMockSubagent({ messages: [{ content: "General result" }] }),
    }

    const bgTool = buildBackgroundTaskTool(registry, subagentGraphs, [
      "- **explore**: Search codebase",
      "- **general**: Multi-step tasks",
    ])

    // Launch 3 tasks in parallel
    const results = await Promise.all([
      bgTool.invoke(
        { description: "Explore area 1", subagent_type: "explore" },
        makeRuntime("call_1"),
      ),
      bgTool.invoke(
        { description: "Explore area 2", subagent_type: "explore" },
        makeRuntime("call_2"),
      ),
      bgTool.invoke(
        { description: "General task", subagent_type: "general" },
        makeRuntime("call_3"),
      ),
    ])

    // All 3 should return Command objects
    for (const [i, result] of results.entries()) {
      expect(result).toBeInstanceOf(Command)
      const cmd = result as Command
      const update = (cmd as any).update ?? (cmd as any)._update
      console.log(`  Task ${i + 1}: Command returned`)

      if (update?.backgroundTasks) {
        const taskIds = Object.keys(update.backgroundTasks)
        console.log(`    Task IDs: ${taskIds.join(", ")}`)
        expect(taskIds).toHaveLength(1) // Each command updates one task
      }
    }

    // Registry should have 3 tasks
    expect(registry.getByNumber(1)).toBeDefined()
    expect(registry.getByNumber(2)).toBeDefined()
    expect(registry.getByNumber(3)).toBeDefined()

    console.log("  [PASS] 3 parallel background tasks launched with unique IDs")
  })

  test("wait for all after parallel launch", async () => {
    const subagentGraphs: Record<string, any> = {
      explore: {
        invoke: () => delay(50).then(() => ({ messages: [{ content: "Explore done" }] })),
      },
      general: {
        invoke: () => delay(100).then(() => ({ messages: [{ content: "General done" }] })),
      },
    }

    const bgTool = buildBackgroundTaskTool(registry, subagentGraphs, ["- explore", "- general"])
    const waitTool = buildWaitTool(registry, 10_000)

    // Launch 3 tasks
    await Promise.all([
      bgTool.invoke({ description: "Task 1", subagent_type: "explore" }, makeRuntime("call_a")),
      bgTool.invoke({ description: "Task 2", subagent_type: "explore" }, makeRuntime("call_b")),
      bgTool.invoke({ description: "Task 3", subagent_type: "general" }, makeRuntime("call_c")),
    ])

    // Wait for all
    const waitResult = await waitTool.invoke({}, makeRuntime("call_wait"))

    // Should be a Command with all results
    if (waitResult instanceof Command) {
      const update = (waitResult as any).update ?? (waitResult as any)._update
      if (update?.messages?.[0]) {
        const content = update.messages[0].content ?? update.messages[0].kwargs?.content
        console.log("  Wait result:", typeof content === "string" ? content.slice(0, 300) : "non-string")
      }
    } else {
      console.log("  Wait result (string):", String(waitResult).slice(0, 300))
    }

    console.log("  [PASS] waitForAll completed after parallel launches")
  })

  test("backgroundTasksReducer merges concurrent updates", () => {
    const existing: Record<string, BackgroundTaskRecord> = {
      "task-1": makeRecord({ taskId: "task-1", taskNumber: 1, status: "running" }),
    }

    // Simulate 3 concurrent updates
    const update1 = { "task-2": makeRecord({ taskId: "task-2", taskNumber: 2, status: "running" }) }
    const update2 = { "task-3": makeRecord({ taskId: "task-3", taskNumber: 3, status: "running" }) }
    const update3 = { "task-1": makeRecord({ taskId: "task-1", taskNumber: 1, status: "success", result: "done" }) }

    let state = backgroundTasksReducer(existing, update1)
    state = backgroundTasksReducer(state, update2)
    state = backgroundTasksReducer(state, update3)

    expect(Object.keys(state)).toHaveLength(3)
    expect(state["task-1"].status).toBe("success")
    expect(state["task-2"].status).toBe("running")
    expect(state["task-3"].status).toBe("running")

    console.log("  [PASS] Reducer correctly merges 3 concurrent updates")
  })
})

// ===========================================================================
// Section 4: Harness Stream Processing — Parallel Tool Call Matching
// ===========================================================================

describe("4. Harness stream — parallel tool call FIFO matching", () => {
  test("3 parallel ToolStarts with same name get matched via FIFO", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const starts = new Map<string, { tool: string; time: number }>()
        const ends = new Map<string, { tool: string; output: string; time: number }>()

        const startUnsub = Bus.subscribe(Harness.Event.ToolStart, (evt) => {
          starts.set(evt.properties.toolCallId, {
            tool: evt.properties.tool,
            time: Date.now(),
          })
        })

        const endUnsub = Bus.subscribe(Harness.Event.ToolEnd, (evt) => {
          ends.set(evt.properties.toolCallId, {
            tool: evt.properties.tool,
            output: evt.properties.output,
            time: Date.now(),
          })
        })

        // Simulate 3 parallel "task" tool starts
        await Promise.all([
          Bus.publish(Harness.Event.ToolStart, {
            sessionID: "test-session",
            toolCallId: "call_task_1",
            tool: "task",
            args: { description: "Explore 1", subagent_type: "explore" },
          }),
          Bus.publish(Harness.Event.ToolStart, {
            sessionID: "test-session",
            toolCallId: "call_task_2",
            tool: "task",
            args: { description: "Explore 2", subagent_type: "explore" },
          }),
          Bus.publish(Harness.Event.ToolStart, {
            sessionID: "test-session",
            toolCallId: "call_task_3",
            tool: "task",
            args: { description: "General work", subagent_type: "general" },
          }),
        ])

        // Simulate 3 ToolEnds (in reverse order)
        await Promise.all([
          Bus.publish(Harness.Event.ToolEnd, {
            sessionID: "test-session",
            toolCallId: "call_task_3",
            tool: "task",
            output: "General result",
          }),
          Bus.publish(Harness.Event.ToolEnd, {
            sessionID: "test-session",
            toolCallId: "call_task_1",
            tool: "task",
            output: "Explore 1 result",
          }),
          Bus.publish(Harness.Event.ToolEnd, {
            sessionID: "test-session",
            toolCallId: "call_task_2",
            tool: "task",
            output: "Explore 2 result",
          }),
        ])

        startUnsub()
        endUnsub()

        // Verify all matched
        const orphaned = [...starts.keys()].filter((id) => !ends.has(id))
        const unmatched = [...ends.keys()].filter((id) => !starts.has(id))

        expect(starts.size).toBe(3)
        expect(ends.size).toBe(3)
        expect(orphaned).toHaveLength(0)
        expect(unmatched).toHaveLength(0)

        console.log(`  [PASS] 3 parallel task ToolStart/ToolEnd pairs matched, 0 orphans`)
      },
    })
  })

  test("re-keying logic: tool_call_chunks IDs → tool_calls IDs", async () => {
    const pendingTools = new Map<string, { name: string; args: string; started: boolean }>()
    const pendingNameToIds = new Map<string, string[]>()

    function trackPendingName(name: string, id: string) {
      const key = canonTool(name)
      let ids = pendingNameToIds.get(key)
      if (!ids) { ids = []; pendingNameToIds.set(key, ids) }
      if (!ids.includes(id)) ids.push(id)
    }

    function untrackPendingName(name: string, id: string) {
      const key = canonTool(name)
      const ids = pendingNameToIds.get(key)
      if (ids) {
        const idx = ids.indexOf(id)
        if (idx !== -1) ids.splice(idx, 1)
        if (ids.length === 0) pendingNameToIds.delete(key)
      }
    }

    function findRekeyCandidate(name: string, newId: string): string | undefined {
      const ids = pendingNameToIds.get(canonTool(name))
      if (!ids) return undefined
      const candidates = ids.filter((id) => {
        if (id === newId || !pendingTools.has(id)) return false
        return sameTool(pendingTools.get(id)?.name, name)
      })
      return candidates.length > 0 ? candidates[0] : undefined
    }

    // Phase 1: tool_call_chunks arrive with streaming IDs "0","1","2"
    pendingTools.set("0", { name: "task", args: '{"subagent_type":"explore"}', started: false })
    trackPendingName("task", "0")
    pendingTools.set("1", { name: "task", args: '{"subagent_type":"explore"}', started: false })
    trackPendingName("task", "1")
    pendingTools.set("2", { name: "task", args: '{"subagent_type":"general"}', started: false })
    trackPendingName("task", "2")

    expect(pendingTools.size).toBe(3)
    expect(pendingNameToIds.get("task")).toHaveLength(3)

    // Phase 2: tool_calls arrive with authoritative IDs
    const authIds = ["call_abc", "call_def", "call_ghi"]
    for (const authId of authIds) {
      const existingId = findRekeyCandidate("task", authId)
      expect(existingId).toBeDefined()

      // Re-key
      const pending = pendingTools.get(existingId!)!
      pendingTools.delete(existingId!)
      untrackPendingName("task", existingId!)
      pendingTools.set(authId, { ...pending, started: true })
      trackPendingName("task", authId)
    }

    // After re-keying: streaming IDs gone, auth IDs present
    expect(pendingTools.has("0")).toBe(false)
    expect(pendingTools.has("1")).toBe(false)
    expect(pendingTools.has("2")).toBe(false)
    expect(pendingTools.has("call_abc")).toBe(true)
    expect(pendingTools.has("call_def")).toBe(true)
    expect(pendingTools.has("call_ghi")).toBe(true)

    // Phase 3: ToolMessages arrive with auth IDs
    for (const authId of authIds) {
      expect(pendingTools.has(authId)).toBe(true)
      pendingTools.delete(authId)
      untrackPendingName("task", authId)
    }

    expect(pendingTools.size).toBe(0)
    expect(pendingNameToIds.size).toBe(0)

    console.log("  [PASS] Re-keying: 3 streaming IDs → 3 auth IDs → 3 ToolMessages, 0 orphans")
  })
})

// ===========================================================================
// Section 5: Background SubAgent Middleware — Full Integration
// ===========================================================================

describe("5. Background SubAgent middleware — full integration", () => {
  test("agent with background middleware — 2 parallel background tasks", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const diag = startDiagnostic("background middleware — 2 parallel tasks")

        // Import the middleware factory
        const { createBackgroundSubAgentMiddleware } = await import("../../src/agent/background-subagents")

        const subagentModel = new CyclingFakeModel([
          new AIMessage({ content: "Background task completed successfully." }),
        ])

        const backend = new LocalShellBackend({ rootDir: tmp.path })

        // Parent model: launches 2 background tasks, then waits for all
        const parentModel = new CyclingFakeModel([
          new AIMessage({
            content: "",
            tool_calls: [
              { id: "call_bg_1", name: "background_task", args: { description: "Explore area 1", subagent_type: "general-purpose" } },
              { id: "call_bg_2", name: "background_task", args: { description: "Explore area 2", subagent_type: "general-purpose" } },
            ],
          }),
          new AIMessage({
            content: "",
            tool_calls: [
              { id: "call_wait", name: "wait_background_task", args: {} },
            ],
          }),
          new AIMessage({
            content: "Both background tasks completed. Here is the combined result.",
          }),
        ])

        try {
          const { middleware: bgMiddleware, registry } = createBackgroundSubAgentMiddleware({
            defaultModel: subagentModel,
            defaultTools: [],
            generalPurposeAgent: true,
          })

          diag.log({ type: "bg_middleware_created" })

          const agent = createMalibuAgent({
            model: parentModel,
            tools: [],
            systemPrompt: "You are a helpful assistant. Use background_task to launch parallel work.",
            checkpointer: false,
            backend,
            subagents: [],
            name: "test-bg-agent",
            isAnthropicModel: false,
            middleware: [bgMiddleware],
          })

          diag.log({ type: "agent_created" })
          console.log("  Agent created with background middleware")

          const stream = await agent.stream(
            { messages: [new HumanMessage("Run 2 background tasks in parallel.")] },
            {
              configurable: { thread_id: "test-bg-" + Date.now() },
              streamMode: "messages",
            },
          )

          let eventCount = 0
          for await (const event of stream) {
            eventCount++
            const [msg] = Array.isArray(event) ? event : [event]

            if (msg instanceof AIMessageChunk) {
              const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)
              const tcs = msg.tool_calls ?? []

              if (content && content !== "[]" && content !== '""') {
                diag.log({ type: "AIMessageChunk:text", content: content.slice(0, 200) })
              }
              for (const tc of tcs) {
                diag.log({
                  type: "AIMessageChunk:tool_call",
                  toolCallId: tc.id,
                  toolName: tc.name,
                  content: JSON.stringify(tc.args).slice(0, 100),
                })
              }
            } else if (msg instanceof ToolMessage) {
              const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)
              diag.log({
                type: "ToolMessage",
                toolCallId: (msg as any).tool_call_id,
                toolName: msg.name,
                content: content.slice(0, 200),
              })
              console.log(`    ToolMessage: ${msg.name} — ${content.slice(0, 80)}`)
            } else {
              diag.log({
                type: `Other:${msg?.constructor?.name ?? "unknown"}`,
                content: JSON.stringify(msg).slice(0, 200),
              })
            }
          }

          diag.log({ type: "stream_end", content: `Total events: ${eventCount}` })
          console.log(`  Stream completed: ${eventCount} events`)

          // Check registry state
          const pending = registry.pendingCount
          console.log(`  Registry pending: ${pending}`)
          diag.log({ type: "registry_state", content: `pending=${pending}` })
        } catch (error: any) {
          diag.markCrash(error)
          console.error("  CRASH:", error.message)
          console.error("  Stack:", error.stack)
        }
      },
    })
  }, 60_000)
})
