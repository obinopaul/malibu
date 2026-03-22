/**
 * Harness Orphan Diagnostic Tests
 *
 * Simulates various streaming scenarios to test ToolStart/ToolEnd pairing
 * and verify the orphan detection mechanism works correctly.
 */
import { describe, expect, test, afterEach } from "bun:test"
import { Bus } from "../../src/bus"
import { Harness } from "../../src/agent/harness"
import { tmpdir } from "../fixture/fixture"
import { Instance } from "../../src/project/instance"
import { sameTool } from "../../src/tool/alias"

afterEach(async () => {
  await Instance.disposeAll()
})

describe("harness-orphan: Bus event pairing", () => {
  test("compatibility aliases share the same logical tool name", () => {
    expect(sameTool("list", "ls")).toBe(true)
    expect(sameTool("read", "read_file")).toBe(true)
    expect(sameTool("write", "write_file")).toBe(true)
    expect(sameTool("edit", "edit_file")).toBe(true)
    expect(sameTool("bash", "execute")).toBe(true)
    expect(sameTool("glob", "grep")).toBe(false)
  })

  test("ToolStart followed by ToolEnd — no orphans", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const events: Array<{ type: string; callId: string; tool: string }> = []

        const startUnsub = Bus.subscribe(Harness.Event.ToolStart, (evt) => {
          events.push({ type: "start", callId: evt.properties.toolCallId, tool: evt.properties.tool })
        })

        const endUnsub = Bus.subscribe(Harness.Event.ToolEnd, (evt) => {
          events.push({ type: "end", callId: evt.properties.toolCallId, tool: evt.properties.tool })
        })

        // Simulate normal flow: start then end
        await Bus.publish(Harness.Event.ToolStart, {
          sessionID: "test-session",
          toolCallId: "call_001",
          tool: "read_file",
          args: { file_path: "/test.txt" },
        })

        await Bus.publish(Harness.Event.ToolEnd, {
          sessionID: "test-session",
          toolCallId: "call_001",
          tool: "read_file",
          output: "file contents",
        })

        startUnsub()
        endUnsub()

        expect(events).toHaveLength(2)
        expect(events[0].type).toBe("start")
        expect(events[1].type).toBe("end")
        expect(events[0].callId).toBe(events[1].callId)
        console.log("Normal flow: ToolStart + ToolEnd paired correctly")
      },
    })
  })

  test("parallel ToolStarts all get matching ToolEnds", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const starts = new Set<string>()
        const ends = new Set<string>()

        const startUnsub = Bus.subscribe(Harness.Event.ToolStart, (evt) => {
          starts.add(evt.properties.toolCallId)
        })

        const endUnsub = Bus.subscribe(Harness.Event.ToolEnd, (evt) => {
          ends.add(evt.properties.toolCallId)
        })

        // Simulate 3 parallel tool starts
        await Promise.all([
          Bus.publish(Harness.Event.ToolStart, {
            sessionID: "test-session",
            toolCallId: "call_A",
            tool: "ls",
            args: {},
          }),
          Bus.publish(Harness.Event.ToolStart, {
            sessionID: "test-session",
            toolCallId: "call_B",
            tool: "read_file",
            args: { file_path: "/a.txt" },
          }),
          Bus.publish(Harness.Event.ToolStart, {
            sessionID: "test-session",
            toolCallId: "call_C",
            tool: "read_file",
            args: { file_path: "/b.txt" },
          }),
        ])

        // Then 3 parallel tool ends (in different order)
        await Promise.all([
          Bus.publish(Harness.Event.ToolEnd, {
            sessionID: "test-session",
            toolCallId: "call_C",
            tool: "read_file",
            output: "content-b",
          }),
          Bus.publish(Harness.Event.ToolEnd, {
            sessionID: "test-session",
            toolCallId: "call_A",
            tool: "ls",
            output: "dir listing",
          }),
          Bus.publish(Harness.Event.ToolEnd, {
            sessionID: "test-session",
            toolCallId: "call_B",
            tool: "read_file",
            output: "content-a",
          }),
        ])

        startUnsub()
        endUnsub()

        // All starts should have matching ends
        const orphaned = [...starts].filter((id) => !ends.has(id))
        const unmatched = [...ends].filter((id) => !starts.has(id))

        expect(orphaned).toHaveLength(0)
        expect(unmatched).toHaveLength(0)
        console.log(`Parallel flow: ${starts.size} starts, ${ends.size} ends, 0 orphans`)
      },
    })
  })

  test("six parallel ToolStarts all get matching ToolEnds", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const starts = new Set<string>()
        const ends = new Set<string>()

        const items = [
          { id: "call_1", tool: "list", args: { path: "/repo" } },
          { id: "call_2", tool: "read", args: { filePath: "/repo/a.ts" } },
          { id: "call_3", tool: "read_file", args: { file_path: "/b.ts" } },
          { id: "call_4", tool: "glob", args: { pattern: "**/*.ts", path: "/repo" } },
          { id: "call_5", tool: "grep", args: { pattern: "TARGET", path: "/repo" } },
          { id: "call_6", tool: "execute", args: { command: "echo six" } },
        ]

        const startUnsub = Bus.subscribe(Harness.Event.ToolStart, (evt) => {
          starts.add(evt.properties.toolCallId)
        })

        const endUnsub = Bus.subscribe(Harness.Event.ToolEnd, (evt) => {
          ends.add(evt.properties.toolCallId)
        })

        await Promise.all(
          items.map((item) =>
            Bus.publish(Harness.Event.ToolStart, {
              sessionID: "test-session",
              toolCallId: item.id,
              tool: item.tool,
              args: item.args,
            }),
          ),
        )

        await Promise.all(
          [...items].reverse().map((item) =>
            Bus.publish(Harness.Event.ToolEnd, {
              sessionID: "test-session",
              toolCallId: item.id,
              tool: item.tool,
              output: `${item.tool} ok`,
            }),
          ),
        )

        startUnsub()
        endUnsub()

        const orphaned = [...starts].filter((id) => !ends.has(id))
        const unmatched = [...ends].filter((id) => !starts.has(id))

        expect(starts.size).toBe(6)
        expect(ends.size).toBe(6)
        expect(orphaned).toHaveLength(0)
        expect(unmatched).toHaveLength(0)
      },
    })
  })

  test("ToolEnd with mismatched ID creates orphan scenario", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const starts = new Map<string, string>()
        const resolved = new Set<string>()

        const startUnsub = Bus.subscribe(Harness.Event.ToolStart, (evt) => {
          starts.set(evt.properties.toolCallId, evt.properties.tool)
        })

        const endUnsub = Bus.subscribe(Harness.Event.ToolEnd, (evt) => {
          if (starts.has(evt.properties.toolCallId)) {
            resolved.add(evt.properties.toolCallId)
          }
        })

        // Start with ID "call_001"
        await Bus.publish(Harness.Event.ToolStart, {
          sessionID: "test-session",
          toolCallId: "call_001",
          tool: "read_file",
          args: { file_path: "/test.txt" },
        })

        // End with DIFFERENT ID "toolu_001" (simulating provider ID format mismatch)
        await Bus.publish(Harness.Event.ToolEnd, {
          sessionID: "test-session",
          toolCallId: "toolu_001",
          tool: "read_file",
          output: "file contents",
        })

        startUnsub()
        endUnsub()

        const orphaned = [...starts.keys()].filter((id) => !resolved.has(id))
        expect(orphaned).toHaveLength(1)
        expect(orphaned[0]).toBe("call_001")
        console.log("ID mismatch scenario: call_001 orphaned because ToolEnd used toolu_001")
        console.log("This confirms ID mismatch is a real orphan vector")
      },
    })
  })

  test("Bus.publish awaits async subscribers", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        let subscriberCompleted = false

        const unsub = Bus.subscribe(Harness.Event.ToolStart, async () => {
          // Simulate async work (like Session.updatePart)
          await new Promise((resolve) => setTimeout(resolve, 50))
          subscriberCompleted = true
        })

        await Bus.publish(Harness.Event.ToolStart, {
          sessionID: "test-session",
          toolCallId: "call_timing",
          tool: "test",
          args: {},
        })

        unsub()

        // After await Bus.publish, the async subscriber should have completed
        expect(subscriberCompleted).toBe(true)
        console.log("Bus.publish correctly awaits async subscribers")
      },
    })
  })
})
