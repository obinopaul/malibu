/**
 * Tests for standalone background-subagents middleware.
 * Uses bun:test (not vitest).
 */
import { describe, expect, test, beforeEach, mock } from "bun:test"
import { Command } from "@langchain/langgraph"
import { ToolMessage } from "@langchain/core/messages"

import {
  BackgroundTaskRegistry,
  BackgroundSubAgentOrchestrator,
  backgroundTasksReducer,
  BACKGROUND_TASK_SYSTEM_PROMPT,
  TERMINAL_STATUSES,
  extractResultContent,
  filterStateForSubagent,
  toolCallIdFromRuntime,
  getExistingRecord,
  mergeRecord,
  buildBackgroundTaskTool,
  buildTaskProgressTool,
  buildWaitTool,
  buildCancelTool,
  type BackgroundTaskRecord,
  type BackgroundTaskStatus,
} from "../../src/agent/background-subagents"

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

function makeRuntimeNoToolCall(state: BackgroundTaskState = {}): any {
  return { state }
}

/**
 * Create a mock subagent graph that resolves with the given result.
 */
function makeMockSubagent(result: Record<string, unknown> = { messages: [] }) {
  return {
    invoke: mock(() => Promise.resolve(result)),
  } as any
}

// ---------------------------------------------------------------------------
// backgroundTasksReducer
// ---------------------------------------------------------------------------

describe("backgroundTasksReducer", () => {
  test("should return update when existing is undefined", () => {
    const record = makeRecord()
    const result = backgroundTasksReducer(undefined, {
      [record.taskId]: record,
    })
    expect(result).toEqual({ "task-uuid-1": record })
  })

  test("should return empty dict when both are undefined", () => {
    const result = backgroundTasksReducer(undefined, undefined)
    expect(result).toEqual({})
  })

  test("should return existing when update is undefined", () => {
    const record = makeRecord()
    const existing = { [record.taskId]: record }
    const result = backgroundTasksReducer(existing, undefined)
    expect(result).toEqual(existing)
  })

  test("should merge update into existing", () => {
    const existing = {
      "task-1": makeRecord({ taskId: "task-1", taskNumber: 1 }),
    }
    const update = {
      "task-2": makeRecord({ taskId: "task-2", taskNumber: 2 }),
    }
    const result = backgroundTasksReducer(existing, update)
    expect(result).toHaveProperty("task-1")
    expect(result).toHaveProperty("task-2")
  })

  test("should overwrite existing task with same key", () => {
    const existing = {
      "task-1": makeRecord({ taskId: "task-1", status: "running" }),
    }
    const update = {
      "task-1": makeRecord({
        taskId: "task-1",
        status: "success",
        result: "done",
      }),
    }
    const result = backgroundTasksReducer(existing, update)
    expect(result["task-1"].status).toBe("success")
    expect(result["task-1"].result).toBe("done")
  })

  test("should not mutate the existing dict", () => {
    const record1 = makeRecord({ taskId: "task-1" })
    const record2 = makeRecord({ taskId: "task-2", taskNumber: 2 })
    const existing = { [record1.taskId]: record1 }
    const frozenExisting = { ...existing }

    backgroundTasksReducer(existing, { [record2.taskId]: record2 })
    expect(existing).toEqual(frozenExisting)
  })
})

// ---------------------------------------------------------------------------
// TERMINAL_STATUSES
// ---------------------------------------------------------------------------

describe("TERMINAL_STATUSES", () => {
  test.each(["success", "error", "cancelled", "timeout"] as const)(
    "should include '%s'",
    (status) => {
      expect(TERMINAL_STATUSES.has(status as BackgroundTaskStatus)).toBe(true)
    },
  )

  test("should not contain running", () => {
    expect(TERMINAL_STATUSES.has("running")).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// BACKGROUND_TASK_SYSTEM_PROMPT
// ---------------------------------------------------------------------------

describe("BACKGROUND_TASK_SYSTEM_PROMPT", () => {
  test("should reference all four tools", () => {
    expect(BACKGROUND_TASK_SYSTEM_PROMPT).toContain("background_task")
    expect(BACKGROUND_TASK_SYSTEM_PROMPT).toContain("task_progress")
    expect(BACKGROUND_TASK_SYSTEM_PROMPT).toContain("wait_background_task")
    expect(BACKGROUND_TASK_SYSTEM_PROMPT).toContain("cancel_background_task")
  })

  test("should contain workflow instructions", () => {
    expect(BACKGROUND_TASK_SYSTEM_PROMPT).toContain("Launch")
    expect(BACKGROUND_TASK_SYSTEM_PROMPT).toContain("Continue working")
    expect(BACKGROUND_TASK_SYSTEM_PROMPT).toContain("Wait")
  })

  test("should explain when to use background_task vs task", () => {
    expect(BACKGROUND_TASK_SYSTEM_PROMPT).toContain("background_task vs task")
  })

  test("should mention cancellation is best-effort", () => {
    expect(BACKGROUND_TASK_SYSTEM_PROMPT).toContain("best-effort")
  })
})

// ---------------------------------------------------------------------------
// extractResultContent
// ---------------------------------------------------------------------------

describe("extractResultContent", () => {
  test("should extract structuredResponse as JSON", () => {
    const result = extractResultContent({
      structuredResponse: { answer: 42 },
    })
    expect(result).toBe('{"answer":42}')
  })

  test("should extract text from last message content string", () => {
    const result = extractResultContent({
      messages: [{ content: "Hello world" }],
    })
    expect(result).toBe("Hello world")
  })

  test("should extract text blocks from array content", () => {
    const result = extractResultContent({
      messages: [
        {
          content: [
            { type: "text", text: "Part 1" },
            { type: "text", text: "Part 2" },
          ],
        },
      ],
    })
    expect(result).toBe("Part 1\nPart 2")
  })

  test("should filter out tool_use, thinking, and redacted_thinking blocks", () => {
    const result = extractResultContent({
      messages: [
        {
          content: [
            { type: "text", text: "Visible" },
            { type: "tool_use", id: "t1", name: "bash", input: {} },
            { type: "thinking", thinking: "hmm" },
            { type: "redacted_thinking", data: "..." },
          ],
        },
      ],
    })
    expect(result).toBe("Visible")
  })

  test("should return 'Task completed' when all blocks are filtered out", () => {
    const result = extractResultContent({
      messages: [
        {
          content: [
            { type: "tool_use", id: "t1", name: "bash", input: {} },
          ],
        },
      ],
    })
    expect(result).toBe("Task completed")
  })

  test("should return 'Task completed' when no messages", () => {
    expect(extractResultContent({})).toBe("Task completed")
    expect(extractResultContent({ messages: [] })).toBe("Task completed")
  })

  test("should return 'Task completed' when last message has empty content", () => {
    const result = extractResultContent({
      messages: [{ content: "" }],
    })
    expect(result).toBe("Task completed")
  })

  test("should JSON-stringify non-text blocks that pass the filter", () => {
    const block = { type: "image_url", url: "https://example.com/img.png" }
    const result = extractResultContent({
      messages: [{ content: [block] }],
    })
    expect(result).toBe(JSON.stringify(block))
  })

  test("should prefer structuredResponse over messages", () => {
    const result = extractResultContent({
      structuredResponse: "preferred",
      messages: [{ content: "not this" }],
    })
    expect(result).toBe('"preferred"')
  })
})

// ---------------------------------------------------------------------------
// filterStateForSubagent
// ---------------------------------------------------------------------------

describe("filterStateForSubagent", () => {
  test("should exclude known state keys", () => {
    const state = {
      messages: [{ content: "hi" }],
      todos: [],
      structuredResponse: null,
      skillsMetadata: {},
      memoryContents: {},
      backgroundTasks: {},
      customField: "keep me",
      anotherField: 42,
    }
    const result = filterStateForSubagent(state)
    expect(result).toEqual({
      customField: "keep me",
      anotherField: 42,
    })
  })

  test("should return empty object for state with only excluded keys", () => {
    const result = filterStateForSubagent({
      messages: [],
      todos: [],
    })
    expect(result).toEqual({})
  })

  test("should pass through all non-excluded keys", () => {
    const state = { foo: "bar", baz: 123 }
    const result = filterStateForSubagent(state)
    expect(result).toEqual(state)
  })
})

// ---------------------------------------------------------------------------
// toolCallIdFromRuntime
// ---------------------------------------------------------------------------

describe("toolCallIdFromRuntime", () => {
  test("should extract from toolCall.id", () => {
    const runtime = { toolCall: { id: "call-1" } } as any
    expect(toolCallIdFromRuntime(runtime)).toBe("call-1")
  })

  test("should fallback to toolCallId", () => {
    const runtime = { toolCallId: "call-2" } as any
    expect(toolCallIdFromRuntime(runtime)).toBe("call-2")
  })

  test("should return empty string when neither present", () => {
    const runtime = {} as any
    expect(toolCallIdFromRuntime(runtime)).toBe("")
  })

  test("should prefer toolCall.id over toolCallId", () => {
    const runtime = {
      toolCall: { id: "preferred" },
      toolCallId: "fallback",
    } as any
    expect(toolCallIdFromRuntime(runtime)).toBe("preferred")
  })
})

// ---------------------------------------------------------------------------
// getExistingRecord
// ---------------------------------------------------------------------------

describe("getExistingRecord", () => {
  test("should return the record for the given taskId", () => {
    const record = makeRecord()
    const state: BackgroundTaskState = {
      backgroundTasks: { "task-uuid-1": record },
    }
    expect(getExistingRecord("task-uuid-1", state)).toBe(record)
  })

  test("should return undefined for unknown taskId", () => {
    const state: BackgroundTaskState = { backgroundTasks: {} }
    expect(getExistingRecord("unknown", state)).toBeUndefined()
  })

  test("should return undefined when backgroundTasks is undefined", () => {
    expect(getExistingRecord("any", {})).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// mergeRecord
// ---------------------------------------------------------------------------

describe("mergeRecord", () => {
  test("should merge updates into existing record", () => {
    const existing = makeRecord({ status: "running" })
    const result = mergeRecord(existing, {
      status: "success",
      result: "done",
    })
    expect(result.status).toBe("success")
    expect(result.result).toBe("done")
    expect(result.taskId).toBe("task-uuid-1")
    expect(result.agentName).toBe("general-purpose")
  })

  test("should create a fallback record when existing is undefined", () => {
    const result = mergeRecord(undefined, {
      taskId: "new-task",
      taskNumber: 5,
      status: "running",
    })
    expect(result.taskId).toBe("new-task")
    expect(result.taskNumber).toBe(5)
    expect(result.status).toBe("running")
    expect(result.agentName).toBe("")
    expect(result.createdAt).toBeDefined()
  })

  test("should not mutate the existing record", () => {
    const existing = makeRecord()
    const originalStatus = existing.status
    mergeRecord(existing, { status: "success" })
    expect(existing.status).toBe(originalStatus)
  })
})

// ---------------------------------------------------------------------------
// BackgroundTaskRegistry
// ---------------------------------------------------------------------------

describe("BackgroundTaskRegistry", () => {
  let registry: BackgroundTaskRegistry

  beforeEach(() => {
    registry = new BackgroundTaskRegistry()
  })

  describe("register", () => {
    test("should assign sequential task numbers", () => {
      const p1 = new Promise(() => {})
      const p2 = new Promise(() => {})
      expect(registry.register("id-1", p1)).toBe(1)
      expect(registry.register("id-2", p2)).toBe(2)
    })

    test("should store promise wrapper", () => {
      const p = new Promise(() => {})
      registry.register("id-1", p)
      const wrapper = registry.get("id-1")
      expect(wrapper).toBeDefined()
      expect(wrapper!.status).toBe("pending")
    })
  })

  describe("getByNumber", () => {
    test("should retrieve task by number", () => {
      const p = new Promise(() => {})
      registry.register("id-1", p)
      const entry = registry.getByNumber(1)
      expect(entry).toBeDefined()
      expect(entry!.taskId).toBe("id-1")
    })

    test("should return undefined for unknown number", () => {
      expect(registry.getByNumber(99)).toBeUndefined()
    })
  })

  describe("getNumber", () => {
    test("should return task number for id", () => {
      registry.register("id-1", new Promise(() => {}))
      expect(registry.getNumber("id-1")).toBe(1)
    })

    test("should return undefined for unknown id", () => {
      expect(registry.getNumber("unknown")).toBeUndefined()
    })
  })

  describe("promise status tracking", () => {
    test("should track fulfilled status", async () => {
      let resolve!: (value: any) => void
      const p = new Promise((r) => {
        resolve = r
      })
      registry.register("id-1", p)

      const result = { messages: [] }
      resolve(result)
      await p

      // Allow microtask to update wrapper
      await new Promise((r) => setTimeout(r, 0))

      const wrapper = registry.get("id-1")!
      expect(wrapper.status).toBe("fulfilled")
      expect(wrapper.result).toBe(result)
    })

    test("should track rejected status", async () => {
      let reject!: (reason: any) => void
      const p = new Promise((_, r) => {
        reject = r
      })
      registry.register("id-1", p)

      reject(new Error("Test error"))
      try {
        await p
      } catch {
        // expected
      }

      await new Promise((r) => setTimeout(r, 0))

      const wrapper = registry.get("id-1")!
      expect(wrapper.status).toBe("rejected")
      expect(wrapper.error).toBeInstanceOf(Error)
      expect(wrapper.error!.message).toBe("Test error")
    })

    test("should wrap non-Error rejections in Error objects", async () => {
      let reject!: (reason: any) => void
      const p = new Promise((_, r) => {
        reject = r
      })
      registry.register("id-1", p)

      reject("string rejection")
      try {
        await p
      } catch {
        // expected
      }

      await new Promise((r) => setTimeout(r, 0))

      const wrapper = registry.get("id-1")!
      expect(wrapper.status).toBe("rejected")
      expect(wrapper.error).toBeInstanceOf(Error)
      expect(wrapper.error!.message).toBe("string rejection")
    })
  })

  describe("waitFor", () => {
    test("should resolve when task completes", async () => {
      let resolve!: (value: any) => void
      const p = new Promise((r) => {
        resolve = r
      })
      registry.register("id-1", p)

      const result = { messages: [], structuredResponse: "done" }
      resolve(result)

      const value = await registry.waitFor("id-1", 5000)
      expect(value).toBe(result)
    })

    test("should throw TIMEOUT on timeout", async () => {
      const p = new Promise(() => {}) // never resolves
      registry.register("id-1", p)

      try {
        await registry.waitFor("id-1", 50)
        throw new Error("should not reach here")
      } catch (err) {
        expect((err as Error).message).toBe("TIMEOUT")
      }
    })

    test("should throw for unknown task", async () => {
      try {
        await registry.waitFor("unknown")
        throw new Error("should not reach here")
      } catch (err) {
        expect((err as Error).message).toContain("No task found")
      }
    })

    test("should return immediately if already fulfilled", async () => {
      let resolve!: (value: any) => void
      const p = new Promise((r) => {
        resolve = r
      })
      registry.register("id-1", p)

      const result = { done: true }
      resolve(result)
      await p
      await new Promise((r) => setTimeout(r, 0))

      const value = await registry.waitFor("id-1", 100)
      expect(value).toBe(result)
    })

    test("should throw immediately if already rejected", async () => {
      let reject!: (reason: any) => void
      const p = new Promise((_, r) => {
        reject = r
      })
      registry.register("id-1", p)

      reject(new Error("already failed"))
      try {
        await p
      } catch {
        // expected
      }
      await new Promise((r) => setTimeout(r, 0))

      try {
        await registry.waitFor("id-1", 100)
        throw new Error("should not reach here")
      } catch (err) {
        expect((err as Error).message).toBe("already failed")
      }
    })
  })

  describe("waitForAll", () => {
    test("should collect results from all tasks", async () => {
      let resolve1!: (value: any) => void
      let resolve2!: (value: any) => void

      const p1 = new Promise((r) => {
        resolve1 = r
      })
      const p2 = new Promise((r) => {
        resolve2 = r
      })

      registry.register("id-1", p1)
      registry.register("id-2", p2)

      resolve1({ result: "one" })
      resolve2({ result: "two" })

      const results = await registry.waitForAll(5000)
      expect(results.size).toBe(2)
      expect(results.get("id-1")).toEqual({ result: "one" })
      expect(results.get("id-2")).toEqual({ result: "two" })
    })

    test("should return empty map when no tasks", async () => {
      const results = await registry.waitForAll(100)
      expect(results.size).toBe(0)
    })

    test("should handle mixed success and timeout", async () => {
      let resolve1!: (value: any) => void
      const p1 = new Promise((r) => {
        resolve1 = r
      })
      const p2 = new Promise(() => {}) // never resolves

      registry.register("id-1", p1)
      registry.register("id-2", p2)

      resolve1({ result: "one" })

      const results = await registry.waitForAll(50)
      expect(results.get("id-1")).toEqual({ result: "one" })
      expect(results.get("id-2")).toEqual({
        error: "Timed out — task may still be running",
      })
    })

    test("should include already-fulfilled and already-rejected tasks", async () => {
      let resolve1!: (value: any) => void
      let reject2!: (reason: any) => void

      const p1 = new Promise((r) => {
        resolve1 = r
      })
      const p2 = new Promise((_, r) => {
        reject2 = r
      })

      registry.register("id-1", p1)
      registry.register("id-2", p2)

      resolve1({ result: "ok" })
      reject2(new Error("failed"))
      await p1
      try {
        await p2
      } catch {
        // expected
      }
      await new Promise((r) => setTimeout(r, 0))

      const results = await registry.waitForAll(100)
      expect(results.get("id-1")).toEqual({ result: "ok" })
      expect(results.get("id-2")).toEqual({ error: "failed" })
    })
  })

  describe("cancel", () => {
    test("should mark pending task as cancelled", () => {
      registry.register("id-1", new Promise(() => {}))
      expect(registry.cancel("id-1")).toBe(true)

      const wrapper = registry.get("id-1")!
      expect(wrapper.status).toBe("rejected")
      expect(wrapper.error!.message).toBe("Cancelled")
    })

    test("should return false for already completed task", async () => {
      let resolve!: (value: any) => void
      const p = new Promise((r) => {
        resolve = r
      })
      registry.register("id-1", p)

      resolve({ done: true })
      await p
      await new Promise((r) => setTimeout(r, 0))

      expect(registry.cancel("id-1")).toBe(false)
    })

    test("should return false for unknown task", () => {
      expect(registry.cancel("unknown")).toBe(false)
    })
  })

  describe("pendingCount", () => {
    test("should count pending tasks", () => {
      registry.register("id-1", new Promise(() => {}))
      registry.register("id-2", new Promise(() => {}))
      expect(registry.pendingCount).toBe(2)
    })

    test("should exclude completed tasks", async () => {
      let resolve!: (value: any) => void
      const p = new Promise((r) => {
        resolve = r
      })
      registry.register("id-1", p)
      registry.register("id-2", new Promise(() => {}))

      resolve({ done: true })
      await p
      await new Promise((r) => setTimeout(r, 0))

      expect(registry.pendingCount).toBe(1)
    })
  })

  describe("hasPending", () => {
    test("should return true when there are pending tasks", () => {
      registry.register("id-1", new Promise(() => {}))
      expect(registry.hasPending).toBe(true)
    })

    test("should return false when no tasks", () => {
      expect(registry.hasPending).toBe(false)
    })
  })

  describe("getAll", () => {
    test("should return a copy of all tasks", () => {
      registry.register("id-1", new Promise(() => {}))
      registry.register("id-2", new Promise(() => {}))
      const all = registry.getAll()
      expect(all.size).toBe(2)
      // Verify it's a copy
      all.delete("id-1")
      expect(registry.get("id-1")).toBeDefined()
    })
  })

  describe("clear", () => {
    test("should remove all tasks and reset numbering", () => {
      registry.register("id-1", new Promise(() => {}))
      registry.register("id-2", new Promise(() => {}))

      registry.clear()

      expect(registry.pendingCount).toBe(0)
      expect(registry.get("id-1")).toBeUndefined()
      expect(registry.getByNumber(1)).toBeUndefined()

      // Numbering should reset
      const num = registry.register("id-3", new Promise(() => {}))
      expect(num).toBe(1)
    })
  })
})

// ---------------------------------------------------------------------------
// buildBackgroundTaskTool
// ---------------------------------------------------------------------------

describe("buildBackgroundTaskTool", () => {
  const toolCallId = "call-bg-1"

  test("should return an error for an unknown agent type", async () => {
    const registry = new BackgroundTaskRegistry()
    const subagentGraphs = { "general-purpose": makeMockSubagent() }
    const bgTool = buildBackgroundTaskTool(registry, subagentGraphs, [
      "- general-purpose: General agent",
    ])

    const result = await bgTool.invoke(
      { description: "do work", subagent_type: "unknown" },
      makeRuntime(toolCallId),
    )

    // When invoked directly, string returns may be wrapped in ToolMessage
    const content =
      result instanceof ToolMessage
        ? String((result as ToolMessage).content)
        : String(result)
    expect(content).toContain("unknown agent type")
    expect(content).toContain("`general-purpose`")
  })

  test("should return a Command on successful launch", async () => {
    const registry = new BackgroundTaskRegistry()
    const mockAgent = makeMockSubagent({ messages: [{ content: "result" }] })
    const subagentGraphs = { "general-purpose": mockAgent }
    const bgTool = buildBackgroundTaskTool(registry, subagentGraphs, [
      "- general-purpose: General agent",
    ])

    const result = await bgTool.invoke(
      { description: "research something", subagent_type: "general-purpose" },
      makeRuntime(toolCallId, { backgroundTasks: {} }),
    )

    expect(result).toBeInstanceOf(Command)
    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>

    // Check task record is in state update
    const tasks = update.backgroundTasks as Record<string, BackgroundTaskRecord>
    const taskIds = Object.keys(tasks)
    expect(taskIds).toHaveLength(1)
    const record = tasks[taskIds[0]]
    expect(record.agentName).toBe("general-purpose")
    expect(record.status).toBe("running")
    expect(record.taskNumber).toBe(1)

    // Check tool message
    const messages = update.messages as ToolMessage[]
    expect(messages).toHaveLength(1)
    expect(messages[0]).toBeInstanceOf(ToolMessage)
    expect(String(messages[0].content)).toContain("Task-1")
    expect(String(messages[0].content)).toContain("Running in background")
  })

  test("should register the task in the registry", async () => {
    const registry = new BackgroundTaskRegistry()
    const subagentGraphs = { "general-purpose": makeMockSubagent() }
    const bgTool = buildBackgroundTaskTool(registry, subagentGraphs, [
      "- general-purpose: General agent",
    ])

    await bgTool.invoke(
      { description: "do work", subagent_type: "general-purpose" },
      makeRuntime(toolCallId),
    )

    expect(registry.getByNumber(1)).toBeDefined()
  })

  test("should truncate descriptions longer than 200 chars", async () => {
    const registry = new BackgroundTaskRegistry()
    const subagentGraphs = { "general-purpose": makeMockSubagent() }
    const bgTool = buildBackgroundTaskTool(registry, subagentGraphs, [
      "- general-purpose: General agent",
    ])

    const longDesc = "a".repeat(250)
    const result = await bgTool.invoke(
      { description: longDesc, subagent_type: "general-purpose" },
      makeRuntime(toolCallId),
    )

    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>
    const tasks = update.backgroundTasks as Record<string, BackgroundTaskRecord>
    const record = Object.values(tasks)[0]
    expect(record.description.length).toBeLessThanOrEqual(203) // 200 + "..."
    expect(record.description).toContain("...")
  })

  test("should return plain string when no toolCallId", async () => {
    const registry = new BackgroundTaskRegistry()
    const subagentGraphs = { "general-purpose": makeMockSubagent() }
    const bgTool = buildBackgroundTaskTool(registry, subagentGraphs, [
      "- general-purpose: General agent",
    ])

    const result = await bgTool.invoke(
      { description: "do work", subagent_type: "general-purpose" },
      makeRuntimeNoToolCall(),
    )

    // When invoked directly (not via ToolNode), string returns stay as strings
    // or get wrapped into ToolMessage depending on LangChain version
    const content =
      result instanceof ToolMessage
        ? String((result as ToolMessage).content)
        : String(result)
    expect(content).toContain("Task-1")
    expect(content).toContain("Running in background")
  })

  test("should pass filtered state to subagent (excluding messages, todos, etc.)", async () => {
    const registry = new BackgroundTaskRegistry()
    const mockAgent = makeMockSubagent()
    const subagentGraphs = { "general-purpose": mockAgent }
    const bgTool = buildBackgroundTaskTool(registry, subagentGraphs, [
      "- general-purpose: General agent",
    ])

    await bgTool.invoke(
      { description: "research", subagent_type: "general-purpose" },
      makeRuntime(toolCallId, {
        // runtime.state includes both excluded and custom keys
      } as any),
    )

    expect(mockAgent.invoke).toHaveBeenCalledTimes(1)
    const invokedState = (mockAgent.invoke as any).mock.calls[0][0]
    // Messages should be a new HumanMessage with the description
    expect(invokedState.messages).toHaveLength(1)
  })

  test("should assign sequential task numbers across multiple launches", async () => {
    const registry = new BackgroundTaskRegistry()
    const subagentGraphs = { "general-purpose": makeMockSubagent() }
    const bgTool = buildBackgroundTaskTool(registry, subagentGraphs, [
      "- general-purpose: General agent",
    ])

    await bgTool.invoke(
      { description: "task 1", subagent_type: "general-purpose" },
      makeRuntime("call-1"),
    )
    await bgTool.invoke(
      { description: "task 2", subagent_type: "general-purpose" },
      makeRuntime("call-2"),
    )

    expect(registry.getByNumber(1)).toBeDefined()
    expect(registry.getByNumber(2)).toBeDefined()
  })
})

// ---------------------------------------------------------------------------
// buildTaskProgressTool
// ---------------------------------------------------------------------------

describe("buildTaskProgressTool", () => {
  const toolCallId = "call-progress-1"

  test("should return error for unknown task number", async () => {
    const registry = new BackgroundTaskRegistry()
    const progressTool = buildTaskProgressTool(registry)

    const result = await progressTool.invoke(
      { task_number: 99 },
      makeRuntime(toolCallId),
    )

    const content =
      result instanceof ToolMessage
        ? String((result as ToolMessage).content)
        : String(result)
    expect(content).toContain("No background task found")
  })

  test("should return Command with running status for pending task", async () => {
    const registry = new BackgroundTaskRegistry()
    registry.register("id-1", new Promise(() => {}))

    const existingRecord = makeRecord({ taskId: "id-1" })
    const progressTool = buildTaskProgressTool(registry)

    const result = await progressTool.invoke(
      { task_number: 1 },
      makeRuntime(toolCallId, { backgroundTasks: { "id-1": existingRecord } }),
    )

    expect(result).toBeInstanceOf(Command)
    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>
    const messages = update.messages as ToolMessage[]
    expect(String(messages[0].content)).toContain("running")
    expect(String(messages[0].content)).toContain("elapsed")
  })

  test("should return Command with result for completed task", async () => {
    const registry = new BackgroundTaskRegistry()
    let resolve!: (value: any) => void
    const p = new Promise((r) => {
      resolve = r
    })
    registry.register("id-1", p)

    resolve({ messages: [{ content: "The answer is 42" }] })
    await p
    await new Promise((r) => setTimeout(r, 0))

    const existingRecord = makeRecord({ taskId: "id-1" })
    const progressTool = buildTaskProgressTool(registry)

    const result = await progressTool.invoke(
      { task_number: 1 },
      makeRuntime(toolCallId, { backgroundTasks: { "id-1": existingRecord } }),
    )

    expect(result).toBeInstanceOf(Command)
    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>

    // State update should mark success
    const tasks = update.backgroundTasks as Record<string, BackgroundTaskRecord>
    expect(tasks["id-1"].status).toBe("success")
    expect(tasks["id-1"].result).toContain("42")

    // Message should contain the result
    const messages = update.messages as ToolMessage[]
    expect(String(messages[0].content)).toContain("completed")
    expect(String(messages[0].content)).toContain("42")
  })

  test("should return Command with error for rejected task", async () => {
    const registry = new BackgroundTaskRegistry()
    let reject!: (reason: any) => void
    const p = new Promise((_, r) => {
      reject = r
    })
    registry.register("id-1", p)

    reject(new Error("Something broke"))
    try {
      await p
    } catch {
      // expected
    }
    await new Promise((r) => setTimeout(r, 0))

    const existingRecord = makeRecord({ taskId: "id-1" })
    const progressTool = buildTaskProgressTool(registry)

    const result = await progressTool.invoke(
      { task_number: 1 },
      makeRuntime(toolCallId, { backgroundTasks: { "id-1": existingRecord } }),
    )

    expect(result).toBeInstanceOf(Command)
    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>
    const tasks = update.backgroundTasks as Record<string, BackgroundTaskRecord>
    expect(tasks["id-1"].status).toBe("error")

    const messages = update.messages as ToolMessage[]
    expect(String(messages[0].content)).toContain("error")
    expect(String(messages[0].content)).toContain("Something broke")
  })

  test("should return cancelled status for cancelled task", async () => {
    const registry = new BackgroundTaskRegistry()
    registry.register("id-1", new Promise(() => {}))
    registry.cancel("id-1")

    const existingRecord = makeRecord({ taskId: "id-1" })
    const progressTool = buildTaskProgressTool(registry)

    const result = await progressTool.invoke(
      { task_number: 1 },
      makeRuntime(toolCallId, { backgroundTasks: { "id-1": existingRecord } }),
    )

    expect(result).toBeInstanceOf(Command)
    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>
    const tasks = update.backgroundTasks as Record<string, BackgroundTaskRecord>
    expect(tasks["id-1"].status).toBe("cancelled")
  })

  test("should merge with existing record (preserve agentName, description)", async () => {
    const registry = new BackgroundTaskRegistry()
    registry.register("id-1", new Promise(() => {}))

    const existingRecord = makeRecord({
      taskId: "id-1",
      agentName: "explore",
      description: "Explore the codebase",
    })

    const progressTool = buildTaskProgressTool(registry)
    const result = await progressTool.invoke(
      { task_number: 1 },
      makeRuntime(toolCallId, { backgroundTasks: { "id-1": existingRecord } }),
    )

    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>
    const tasks = update.backgroundTasks as Record<string, BackgroundTaskRecord>
    // Should preserve the existing fields
    expect(tasks["id-1"].agentName).toBe("explore")
    expect(tasks["id-1"].description).toBe("Explore the codebase")
  })
})

// ---------------------------------------------------------------------------
// buildWaitTool
// ---------------------------------------------------------------------------

describe("buildWaitTool", () => {
  const toolCallId = "call-wait-1"

  test("should return error for unknown task number", async () => {
    const registry = new BackgroundTaskRegistry()
    const waitTool = buildWaitTool(registry, 120_000)

    const result = await waitTool.invoke(
      { task_number: 99 },
      makeRuntime(toolCallId),
    )

    const content =
      result instanceof ToolMessage
        ? String((result as ToolMessage).content)
        : String(result)
    expect(content).toContain("No background task found")
  })

  test("should return result for already-completed task", async () => {
    const registry = new BackgroundTaskRegistry()
    let resolve!: (value: any) => void
    const p = new Promise((r) => {
      resolve = r
    })
    registry.register("id-1", p)

    resolve({ messages: [{ content: "done" }] })
    await p
    await new Promise((r) => setTimeout(r, 0))

    const existingRecord = makeRecord({ taskId: "id-1" })
    const waitTool = buildWaitTool(registry, 120_000)

    const result = await waitTool.invoke(
      { task_number: 1 },
      makeRuntime(toolCallId, { backgroundTasks: { "id-1": existingRecord } }),
    )

    expect(result).toBeInstanceOf(Command)
    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>
    const tasks = update.backgroundTasks as Record<string, BackgroundTaskRecord>
    expect(tasks["id-1"].status).toBe("success")
  })

  test("should wait and return result for pending task", async () => {
    const registry = new BackgroundTaskRegistry()
    let resolve!: (value: any) => void
    const p = new Promise((r) => {
      resolve = r
    })
    registry.register("id-1", p)

    // Resolve after a short delay
    setTimeout(
      () => resolve({ messages: [{ content: "delayed result" }] }),
      10,
    )

    const existingRecord = makeRecord({ taskId: "id-1" })
    const waitTool = buildWaitTool(registry, 5000)

    const result = await waitTool.invoke(
      { task_number: 1 },
      makeRuntime(toolCallId, { backgroundTasks: { "id-1": existingRecord } }),
    )

    expect(result).toBeInstanceOf(Command)
    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>
    const messages = update.messages as ToolMessage[]
    expect(String(messages[0].content)).toContain("completed")
    expect(String(messages[0].content)).toContain("delayed result")
  })

  test("should return timeout error when task exceeds timeout", async () => {
    const registry = new BackgroundTaskRegistry()
    registry.register("id-1", new Promise(() => {})) // never resolves

    const existingRecord = makeRecord({ taskId: "id-1" })
    const waitTool = buildWaitTool(registry, 50)

    const result = await waitTool.invoke(
      { task_number: 1 },
      makeRuntime(toolCallId, { backgroundTasks: { "id-1": existingRecord } }),
    )

    expect(result).toBeInstanceOf(Command)
    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>
    const tasks = update.backgroundTasks as Record<string, BackgroundTaskRecord>
    expect(tasks["id-1"].status).toBe("timeout")

    const messages = update.messages as ToolMessage[]
    expect(String(messages[0].content)).toContain("timed out")
  })

  test("should use custom timeout_ms from input", async () => {
    const registry = new BackgroundTaskRegistry()
    registry.register("id-1", new Promise(() => {})) // never resolves

    const existingRecord = makeRecord({ taskId: "id-1" })
    const waitTool = buildWaitTool(registry, 120_000) // default is long

    const result = await waitTool.invoke(
      { task_number: 1, timeout_ms: 30 }, // override with very short
      makeRuntime(toolCallId, { backgroundTasks: { "id-1": existingRecord } }),
    )

    expect(result).toBeInstanceOf(Command)
    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>
    const tasks = update.backgroundTasks as Record<string, BackgroundTaskRecord>
    expect(tasks["id-1"].status).toBe("timeout")
  })

  test("should wait for ALL pending tasks when no task_number", async () => {
    const registry = new BackgroundTaskRegistry()
    let resolve1!: (value: any) => void
    let resolve2!: (value: any) => void
    const p1 = new Promise((r) => {
      resolve1 = r
    })
    const p2 = new Promise((r) => {
      resolve2 = r
    })
    registry.register("id-1", p1)
    registry.register("id-2", p2)

    const record1 = makeRecord({ taskId: "id-1", taskNumber: 1 })
    const record2 = makeRecord({ taskId: "id-2", taskNumber: 2 })

    resolve1({ messages: [{ content: "result 1" }] })
    resolve2({ messages: [{ content: "result 2" }] })

    const waitTool = buildWaitTool(registry, 5000)

    const result = await waitTool.invoke(
      {},
      makeRuntime(toolCallId, {
        backgroundTasks: { "id-1": record1, "id-2": record2 },
      }),
    )

    expect(result).toBeInstanceOf(Command)
    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>
    const messages = update.messages as ToolMessage[]
    const content = String(messages[0].content)
    expect(content).toContain("Task-1")
    expect(content).toContain("Task-2")
    expect(content).toContain("result 1")
    expect(content).toContain("result 2")
  })

  test("should return 'No background tasks' when waiting all with no tasks", async () => {
    const registry = new BackgroundTaskRegistry()
    const waitTool = buildWaitTool(registry, 5000)

    const result = await waitTool.invoke({}, makeRuntime(toolCallId))

    expect(result).toBeInstanceOf(Command)
    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>
    const messages = update.messages as ToolMessage[]
    expect(String(messages[0].content)).toContain("No background tasks")
  })

  test("should handle already-rejected task in wait", async () => {
    const registry = new BackgroundTaskRegistry()
    let reject!: (reason: any) => void
    const p = new Promise((_, r) => {
      reject = r
    })
    registry.register("id-1", p)

    reject(new Error("task failed"))
    try {
      await p
    } catch {
      // expected
    }
    await new Promise((r) => setTimeout(r, 0))

    const existingRecord = makeRecord({ taskId: "id-1" })
    const waitTool = buildWaitTool(registry, 5000)

    const result = await waitTool.invoke(
      { task_number: 1 },
      makeRuntime(toolCallId, { backgroundTasks: { "id-1": existingRecord } }),
    )

    expect(result).toBeInstanceOf(Command)
    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>
    const tasks = update.backgroundTasks as Record<string, BackgroundTaskRecord>
    expect(tasks["id-1"].status).toBe("error")
  })

  test("should return plain string when no toolCallId (wait-all)", async () => {
    const registry = new BackgroundTaskRegistry()
    const waitTool = buildWaitTool(registry, 5000)

    const result = await waitTool.invoke({}, makeRuntimeNoToolCall())

    const content =
      result instanceof ToolMessage
        ? String((result as ToolMessage).content)
        : String(result)
    expect(content).toContain("No background tasks")
  })
})

// ---------------------------------------------------------------------------
// buildCancelTool
// ---------------------------------------------------------------------------

describe("buildCancelTool", () => {
  const toolCallId = "call-cancel-1"

  test("should return error for unknown task number", async () => {
    const registry = new BackgroundTaskRegistry()
    const cancelTool = buildCancelTool(registry)

    const result = await cancelTool.invoke(
      { task_number: 99 },
      makeRuntime(toolCallId),
    )

    const content =
      result instanceof ToolMessage
        ? String((result as ToolMessage).content)
        : String(result)
    expect(content).toContain("No background task found")
  })

  test("should cancel a pending task and return Command", async () => {
    const registry = new BackgroundTaskRegistry()
    registry.register("id-1", new Promise(() => {}))

    const existingRecord = makeRecord({ taskId: "id-1" })
    const cancelTool = buildCancelTool(registry)

    const result = await cancelTool.invoke(
      { task_number: 1 },
      makeRuntime(toolCallId, { backgroundTasks: { "id-1": existingRecord } }),
    )

    expect(result).toBeInstanceOf(Command)
    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>

    const tasks = update.backgroundTasks as Record<string, BackgroundTaskRecord>
    expect(tasks["id-1"].status).toBe("cancelled")
    expect(tasks["id-1"].completedAt).toBeDefined()

    const messages = update.messages as ToolMessage[]
    expect(String(messages[0].content)).toContain("cancelled")
  })

  test("should refuse to cancel already-completed task", async () => {
    const registry = new BackgroundTaskRegistry()
    let resolve!: (value: any) => void
    const p = new Promise((r) => {
      resolve = r
    })
    registry.register("id-1", p)

    resolve({ done: true })
    await p
    await new Promise((r) => setTimeout(r, 0))

    const cancelTool = buildCancelTool(registry)
    const result = await cancelTool.invoke(
      { task_number: 1 },
      makeRuntime(toolCallId),
    )

    const content =
      result instanceof ToolMessage
        ? String((result as ToolMessage).content)
        : String(result)
    expect(content).toContain("already")
    expect(content).toContain("cannot cancel")
  })

  test("should preserve existing record fields on cancel", async () => {
    const registry = new BackgroundTaskRegistry()
    registry.register("id-1", new Promise(() => {}))

    const existingRecord = makeRecord({
      taskId: "id-1",
      agentName: "explore",
      description: "Search codebase",
    })

    const cancelTool = buildCancelTool(registry)
    const result = await cancelTool.invoke(
      { task_number: 1 },
      makeRuntime(toolCallId, { backgroundTasks: { "id-1": existingRecord } }),
    )

    const cmd = result as Command
    const update = cmd.update as Record<string, unknown>
    const tasks = update.backgroundTasks as Record<string, BackgroundTaskRecord>
    expect(tasks["id-1"].agentName).toBe("explore")
    expect(tasks["id-1"].description).toBe("Search codebase")
    expect(tasks["id-1"].status).toBe("cancelled")
  })
})

// ---------------------------------------------------------------------------
// BackgroundSubAgentOrchestrator
// ---------------------------------------------------------------------------

describe("BackgroundSubAgentOrchestrator", () => {
  test("should return agent result when no pending tasks", async () => {
    const registry = new BackgroundTaskRegistry()
    const orchestrator = new BackgroundSubAgentOrchestrator(registry)

    const agentResult = { messages: [{ content: "done" }] }
    const mockAgent = { invoke: mock(() => Promise.resolve(agentResult)) }

    const result = await orchestrator.invoke(mockAgent as any, {
      messages: [],
    })

    expect(result).toBe(agentResult)
    expect(mockAgent.invoke).toHaveBeenCalledTimes(1)
  })

  test("should re-invoke agent when pending tasks exist", async () => {
    const registry = new BackgroundTaskRegistry()
    const orchestrator = new BackgroundSubAgentOrchestrator(registry, 5000, 3)

    const firstResult = {
      messages: [{ content: "agent first response" }],
    }
    const secondResult = {
      messages: [{ content: "agent synthesis" }],
    }

    // Create a deferred that resolves shortly after registration
    let deferredResolve!: (value: any) => void
    const deferredPromise = new Promise((r) => {
      deferredResolve = r
    })

    let callCount = 0
    const mockAgent = {
      invoke: mock(async () => {
        callCount++
        if (callCount === 1) {
          // Register a task that is still pending when invoke returns
          registry.register("id-1", deferredPromise)
          return firstResult
        }
        return secondResult
      }),
    }

    // Resolve the deferred shortly after — orchestrator's waitForAll will pick it up
    setTimeout(
      () => deferredResolve({ messages: [{ content: "bg result" }] }),
      10,
    )

    const result = await orchestrator.invoke(mockAgent as any, {
      messages: [],
    })

    // Should have been invoked twice: initial + re-invoke with results
    expect(mockAgent.invoke).toHaveBeenCalledTimes(2)
    expect(result).toBe(secondResult)

    // Second invocation should include background task results
    const secondCallInput = (mockAgent.invoke as any).mock.calls[1][0]
    const lastMessage =
      secondCallInput.messages[secondCallInput.messages.length - 1]
    expect(lastMessage.content).toContain("Background Task Results")
    expect(lastMessage.content).toContain("bg result")
  })

  test("should respect maxReinvocations limit", async () => {
    const registry = new BackgroundTaskRegistry()
    const orchestrator = new BackgroundSubAgentOrchestrator(registry, 50, 2)

    let taskRegistered = false
    const mockAgent = {
      invoke: mock(async () => {
        // Register a never-resolving task on first call
        if (!taskRegistered) {
          registry.register("id-never", new Promise(() => {}))
          taskRegistered = true
        }
        return { messages: [{ content: "response" }] }
      }),
    }

    await orchestrator.invoke(mockAgent as any, { messages: [] })

    // 1 initial + 2 re-invocations = 3 total calls max
    expect(mockAgent.invoke).toHaveBeenCalledTimes(3)
  })

  test("should stop re-invoking when no more pending tasks", async () => {
    const registry = new BackgroundTaskRegistry()
    const orchestrator = new BackgroundSubAgentOrchestrator(registry, 5000, 5)

    let deferredResolve!: (value: any) => void
    const deferredPromise = new Promise((r) => {
      deferredResolve = r
    })

    let callCount = 0
    const mockAgent = {
      invoke: mock(async () => {
        callCount++
        if (callCount === 1) {
          registry.register("id-1", deferredPromise)
          return { messages: [{ content: "response" }] }
        }
        return { messages: [{ content: "synthesis" }] }
      }),
    }

    // Resolve shortly after so waitForAll picks it up
    setTimeout(
      () => deferredResolve({ messages: [{ content: "result" }] }),
      10,
    )

    await orchestrator.invoke(mockAgent as any, { messages: [] })

    // Only 2 calls: initial + one re-invoke (tasks all done after first wait)
    expect(mockAgent.invoke).toHaveBeenCalledTimes(2)
  })

  test("should pass config through to agent.invoke", async () => {
    const registry = new BackgroundTaskRegistry()
    const orchestrator = new BackgroundSubAgentOrchestrator(registry)

    const mockAgent = {
      invoke: mock(() => Promise.resolve({ messages: [] })),
    }
    const config = { configurable: { thread_id: "test" } }

    await orchestrator.invoke(mockAgent as any, { messages: [] }, config)

    expect(mockAgent.invoke).toHaveBeenCalledWith(expect.any(Object), config)
  })

  test("should include error tasks in re-invocation message", async () => {
    const registry = new BackgroundTaskRegistry()
    const orchestrator = new BackgroundSubAgentOrchestrator(registry, 5000, 3)

    const secondResult = { messages: [{ content: "synthesis" }] }

    let deferredReject!: (reason: any) => void
    const deferredPromise = new Promise((_, r) => {
      deferredReject = r
    })

    let callCount = 0
    const mockAgent = {
      invoke: mock(async () => {
        callCount++
        if (callCount === 1) {
          registry.register("id-1", deferredPromise)
          return { messages: [{ content: "first" }] }
        }
        return secondResult
      }),
    }

    // Reject shortly after so waitForAll picks it up
    setTimeout(() => deferredReject(new Error("task crashed")), 10)

    await orchestrator.invoke(mockAgent as any, { messages: [] })

    expect(mockAgent.invoke).toHaveBeenCalledTimes(2)
    const secondCallInput = (mockAgent.invoke as any).mock.calls[1][0]
    const lastMessage =
      secondCallInput.messages[secondCallInput.messages.length - 1]
    expect(lastMessage.content).toContain("error")
    expect(lastMessage.content).toContain("task crashed")
  })
})
