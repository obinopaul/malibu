import { describe, expect, test } from "bun:test"
import { Harness } from "../../src/agent/harness"
import { HumanMessage, AIMessage, ToolMessage, SystemMessage } from "@langchain/core/messages"
import type { MessageV2 } from "../../src/session/message-v2"

describe("harness.convertMessages", () => {
  test("converts user text messages to HumanMessage", () => {
    const messages: MessageV2.WithParts[] = [
      {
        info: { id: "m1", role: "user", sessionID: "s1", time: { created: Date.now() } } as any,
        parts: [
          { id: "p1", messageID: "m1", sessionID: "s1", type: "text", text: "Hello world" },
        ] as any[],
      },
    ]

    const result = Harness.convertMessages(messages)
    expect(result).toHaveLength(1)
    expect(result[0]).toBeInstanceOf(HumanMessage)
    expect(result[0].content).toBe("Hello world")
  })

  test("converts assistant text messages to AIMessage", () => {
    const messages: MessageV2.WithParts[] = [
      {
        info: { id: "m1", role: "assistant", sessionID: "s1", time: { created: Date.now() } } as any,
        parts: [
          { id: "p1", messageID: "m1", sessionID: "s1", type: "text", text: "I can help" },
        ] as any[],
      },
    ]

    const result = Harness.convertMessages(messages)
    expect(result).toHaveLength(1)
    expect(result[0]).toBeInstanceOf(AIMessage)
    expect(result[0].content).toBe("I can help")
  })

  test("converts assistant tool calls to AIMessage + ToolMessage pairs", () => {
    const messages: MessageV2.WithParts[] = [
      {
        info: { id: "m1", role: "assistant", sessionID: "s1", time: { created: Date.now() } } as any,
        parts: [
          { id: "p1", messageID: "m1", sessionID: "s1", type: "text", text: "Let me check" },
          {
            id: "p2",
            messageID: "m1",
            sessionID: "s1",
            type: "tool",
            tool: "read",
            callID: "tc-1",
            state: {
              status: "completed",
              input: { filePath: "/foo.ts" },
              output: "file contents",
              time: { start: 0, end: 1 },
            },
          },
        ] as any[],
      },
    ]

    const result = Harness.convertMessages(messages)
    expect(result).toHaveLength(2)
    expect(result[0]).toBeInstanceOf(AIMessage)
    expect((result[0] as AIMessage).tool_calls).toHaveLength(1)
    expect((result[0] as AIMessage).tool_calls![0].name).toBe("read")
    expect(result[1]).toBeInstanceOf(ToolMessage)
    expect(result[1].content).toBe("file contents")
  })

  test("skips empty user messages", () => {
    const messages: MessageV2.WithParts[] = [
      {
        info: { id: "m1", role: "user", sessionID: "s1", time: { created: Date.now() } } as any,
        parts: [] as any[],
      },
    ]

    const result = Harness.convertMessages(messages)
    expect(result).toHaveLength(0)
  })

  test("converts summary parts to SystemMessage", () => {
    const messages: MessageV2.WithParts[] = [
      {
        info: { id: "m1", role: "assistant", sessionID: "s1", time: { created: Date.now() } } as any,
        parts: [
          { id: "p1", messageID: "m1", sessionID: "s1", type: "summary", text: "Summary of work" },
        ] as any[],
      },
    ]

    const result = Harness.convertMessages(messages)
    expect(result).toHaveLength(1)
    expect(result[0]).toBeInstanceOf(SystemMessage)
    expect(result[0].content).toContain("Summary of work")
  })
})
