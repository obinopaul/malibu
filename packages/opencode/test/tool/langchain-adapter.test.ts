import { describe, expect, test, beforeEach } from "bun:test"
import { ToolMessage } from "@langchain/core/messages"
import z from "zod"
import {
  toLangChainTool,
  toolMetadataStore,
  metadataKey,
  clearSessionMetadata,
} from "../../src/tool/langchain-adapter"
import { SessionID, MessageID } from "../../src/session/schema"
import { Tool } from "../../src/tool/tool"

describe("langchain-adapter.toolMetadataStore", () => {
  beforeEach(() => {
    toolMetadataStore.clear()
  })

  test("metadataKey creates scoped key", () => {
    const key = metadataKey("session-1", "call-1")
    expect(key).toBe("session-1:call-1")
  })

  test("set and get metadata", () => {
    const key = metadataKey("s1", "c1")
    toolMetadataStore.set(key, {
      title: "test-tool",
      metadata: { foo: "bar" },
      timestamp: Date.now(),
    })
    const result = toolMetadataStore.get(key)
    expect(result?.title).toBe("test-tool")
    expect(result?.metadata?.foo).toBe("bar")
  })

  test("clearSessionMetadata removes all entries for a session", () => {
    toolMetadataStore.set(metadataKey("s1", "c1"), { title: "a", timestamp: Date.now() })
    toolMetadataStore.set(metadataKey("s1", "c2"), { title: "b", timestamp: Date.now() })
    toolMetadataStore.set(metadataKey("s2", "c3"), { title: "c", timestamp: Date.now() })

    expect(toolMetadataStore.size).toBe(3)
    clearSessionMetadata("s1")
    expect(toolMetadataStore.size).toBe(1)
    expect(toolMetadataStore.has(metadataKey("s2", "c3"))).toBe(true)
  })

  test("clearSessionMetadata is idempotent", () => {
    toolMetadataStore.set(metadataKey("s1", "c1"), { title: "a", timestamp: Date.now() })
    clearSessionMetadata("s1")
    clearSessionMetadata("s1")
    expect(toolMetadataStore.size).toBe(0)
  })
})

describe("langchain-adapter.metadataKey isolation", () => {
  test("different sessions produce different keys", () => {
    const k1 = metadataKey("session-a", "call-1")
    const k2 = metadataKey("session-b", "call-1")
    expect(k1).not.toBe(k2)
  })

  test("different calls in same session produce different keys", () => {
    const k1 = metadataKey("session-a", "call-1")
    const k2 = metadataKey("session-a", "call-2")
    expect(k1).not.toBe(k2)
  })
})

describe("langchain-adapter.tool errors", () => {
  beforeEach(() => {
    toolMetadataStore.clear()
  })

  function bridge() {
    return {
      sessionID: SessionID.make("session-1"),
      messageID: MessageID.make("message-1"),
      agent: "build",
      abort: new AbortController().signal,
      messages: [],
    }
  }

  function text(input: unknown) {
    if (typeof input === "string") return input
    if (input instanceof ToolMessage) {
      if (typeof input.content === "string") return input.content
      return JSON.stringify(input.content)
    }
    return JSON.stringify(input)
  }

  test("returns a ToolMessage for validation failures", async () => {
    const info = Tool.define("demo", {
      description: "Demo tool",
      parameters: z.object({
        value: z.string(),
      }),
      async execute(args) {
        return {
          title: "Demo",
          metadata: {},
          output: args.value,
        }
      },
    })

    const tool = await toLangChainTool(info, bridge())
    const result = await tool.invoke({
      type: "tool_call",
      id: "call-1",
      name: "demo",
      args: {},
    } as any)

    expect(result).toBeInstanceOf(ToolMessage)
    expect(text(result)).toContain("Received tool input did not match expected schema")
    expect(toolMetadataStore.get(metadataKey("session-1", "call-1"))?.status).toBe("error")
  })

  test("stores error status for execution failures", async () => {
    const info = Tool.define("explode", {
      description: "Explode tool",
      parameters: z.object({
        value: z.string(),
      }),
      async execute() {
        throw new Error("boom")
      },
    })

    const tool = await toLangChainTool(info, bridge())
    const result = await tool.invoke({
      type: "tool_call",
      id: "call-2",
      name: "explode",
      args: {
        value: "x",
      },
    } as any)

    expect(text(result)).toContain("Error: boom")
    expect(toolMetadataStore.get(metadataKey("session-1", "call-2"))?.status).toBe("error")
  })

  test("stores completed status for successful tool calls", async () => {
    const info = Tool.define("ok", {
      description: "Ok tool",
      parameters: z.object({
        value: z.string(),
      }),
      async execute(args) {
        return {
          title: "Ok",
          metadata: { value: args.value },
          output: `ok:${args.value}`,
        }
      },
    })

    const tool = await toLangChainTool(info, bridge())
    const result = await tool.invoke({
      type: "tool_call",
      id: "call-3",
      name: "ok",
      args: {
        value: "done",
      },
    } as any)

    expect(text(result)).toContain("ok:done")
    expect(toolMetadataStore.get(metadataKey("session-1", "call-3"))?.status).toBe("completed")
  })
})
