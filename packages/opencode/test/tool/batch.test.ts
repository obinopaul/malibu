import { afterEach, describe, expect, test } from "bun:test"
import fs from "fs/promises"
import path from "path"
import { Instance } from "../../src/project/instance"
import { ProviderID, ModelID } from "../../src/provider/schema"
import { Session } from "../../src/session"
import { MessageV2 } from "../../src/session/message-v2"
import { MessageID } from "../../src/session/schema"
import { BatchTool } from "../../src/tool/batch"
import type { Tool } from "../../src/tool/tool"
import { tmpdir } from "../fixture/fixture"

afterEach(async () => {
  await Instance.disposeAll()
})

function ctx(input: { sessionID: Tool.Context["sessionID"]; messageID: Tool.Context["messageID"] }): Tool.Context {
  return {
    sessionID: input.sessionID,
    messageID: input.messageID,
    agent: "build",
    abort: new AbortController().signal,
    messages: [],
    metadata: () => {},
    ask: async () => {},
  }
}

async function msg(sessionID: Tool.Context["sessionID"]) {
  const model = {
    providerID: ProviderID.make("openai"),
    modelID: ModelID.make("gpt-5.2"),
  }
  const user = await Session.updateMessage({
    id: MessageID.ascending(),
    sessionID,
    role: "user",
    time: {
      created: Date.now(),
    },
    agent: "build",
    model,
  })
  return Session.updateMessage({
    id: MessageID.ascending(),
    sessionID,
    parentID: user.id,
    role: "assistant",
    mode: "build",
    agent: "build",
    path: {
      cwd: Instance.directory,
      root: Instance.worktree,
    },
    cost: 0,
    tokens: {
      input: 0,
      output: 0,
      reasoning: 0,
      cache: { read: 0, write: 0 },
    },
    modelID: model.modelID,
    providerID: model.providerID,
    time: {
      created: Date.now(),
    },
  })
}

describe("tool.batch", () => {
  test("runs seven tool calls in parallel and records completed parts", async () => {
    await using tmp = await tmpdir({
      git: true,
      config: {
        experimental: {
          batch_tool: true,
        },
      },
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "a.txt"), "alpha\n")
        await fs.writeFile(path.join(dir, "b.txt"), "beta\n")
        await fs.mkdir(path.join(dir, "src"), { recursive: true })
        await fs.writeFile(path.join(dir, "src", "main.ts"), "export const TARGET = true\n")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const ses = await Session.create({})
        const out = await msg(ses.id)
        const tool = await BatchTool.init()
        const result = await tool.execute(
          {
            tool_calls: [
              { tool: "list", parameters: { path: tmp.path } },
              { tool: "ls", parameters: { path: "/" } },
              { tool: "read", parameters: { filePath: path.join(tmp.path, "a.txt") } },
              { tool: "read_file", parameters: { file_path: "/b.txt" } },
              { tool: "glob", parameters: { pattern: "**/*.ts", path: tmp.path } },
              { tool: "grep", parameters: { pattern: "TARGET", path: tmp.path } },
              { tool: "execute", parameters: { command: "echo batch-ok" } },
            ],
          },
          ctx({ sessionID: ses.id, messageID: out.id }),
        )

        expect(result.output).toContain("All 7 tools executed successfully")
        expect(result.metadata.totalCalls).toBe(7)
        expect(result.metadata.successful).toBe(7)
        expect(result.metadata.failed).toBe(0)

        const parts = (await MessageV2.parts(out.id)).filter((part): part is MessageV2.ToolPart => part.type === "tool")
        expect(parts).toHaveLength(7)
        expect(parts.every((part) => part.state.status === "completed")).toBe(true)

        const map = new Map(parts.map((part) => [part.tool, part]))
        expect((map.get("read")?.state as MessageV2.ToolStateCompleted).output).toContain("alpha")
        expect((map.get("read_file")?.state as MessageV2.ToolStateCompleted).output).toContain("beta")
        expect((map.get("grep")?.state as MessageV2.ToolStateCompleted).output).toContain("TARGET")
        expect((map.get("execute")?.state as MessageV2.ToolStateCompleted).output).toContain("batch-ok")

        await Session.remove(ses.id)
      },
    })
  })

  test("captures a malformed inner call alongside five successful calls", async () => {
    await using tmp = await tmpdir({
      git: true,
      config: {
        experimental: {
          batch_tool: true,
        },
      },
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "b.txt"), "beta\n")
        await fs.mkdir(path.join(dir, "src"), { recursive: true })
        await fs.writeFile(path.join(dir, "src", "main.ts"), "export const TARGET = true\n")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const ses = await Session.create({})
        const out = await msg(ses.id)
        const tool = await BatchTool.init()
        const result = await tool.execute(
          {
            tool_calls: [
              { tool: "list", parameters: { path: tmp.path } },
              { tool: "read_file", parameters: { file_path: "/b.txt" } },
              { tool: "glob", parameters: { pattern: "**/*.ts", path: tmp.path } },
              { tool: "grep", parameters: { pattern: "TARGET", path: tmp.path } },
              { tool: "execute", parameters: { command: "echo batch-mixed" } },
              { tool: "read", parameters: {} },
            ],
          },
          ctx({ sessionID: ses.id, messageID: out.id }),
        )

        expect(result.output).toContain("Executed 5/6 tools successfully. 1 failed.")
        expect(result.output).toContain("<batch_failures>")
        expect(result.output).toContain("tool: read")
        expect(result.output).toContain("error:")
        expect(result.output).toContain("filePath")
        expect(result.metadata.totalCalls).toBe(6)
        expect(result.metadata.successful).toBe(5)
        expect(result.metadata.failed).toBe(1)

        const parts = (await MessageV2.parts(out.id)).filter((part): part is MessageV2.ToolPart => part.type === "tool")
        expect(parts).toHaveLength(6)

        const err = parts.find((part) => part.tool === "read" && part.state.status === "error")
        expect(err).toBeTruthy()
        if (!err || err.state.status !== "error") throw new Error("missing read error part")

        expect(err.state.input).toEqual({})
        expect(err.state.error).toContain("filePath")
        expect(parts.filter((part) => part.state.status === "completed")).toHaveLength(5)

        await Session.remove(ses.id)
      },
    })
  })
})
