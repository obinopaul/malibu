import { afterEach, describe, expect, test } from "bun:test"
import path from "path"
import fs from "fs/promises"
import { tmpdir } from "../fixture/fixture"
import { Instance } from "../../src/project/instance"
import { ToolRegistry } from "../../src/tool/registry"

afterEach(async () => {
  await Instance.disposeAll()
})

describe("tool.registry", () => {
  test("registers native Malibu tools (no wrapper tools)", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const ids = await ToolRegistry.ids()
        expect(ids).toContain("list")
        expect(ids).toContain("read")
        expect(ids).toContain("write")
        expect(ids).toContain("edit")
        expect(ids).toContain("bash")
        expect(ids).toContain("glob")
        expect(ids).toContain("grep")
        expect(ids).not.toContain("ls")
        expect(ids).not.toContain("read_file")
        expect(ids).not.toContain("write_file")
        expect(ids).not.toContain("edit_file")
        expect(ids).not.toContain("execute")
      },
    })
  })

  test("keeps intentionally unexposed tools out of the registry", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const ids = await ToolRegistry.ids()
        expect(ids).not.toContain("multiedit")
        expect(ids).not.toContain("todoread")
        expect(ids).not.toContain("plan_enter")
      },
    })
  })

  test("loads tools from .malibu/tool (singular)", async () => {
    await using tmp = await tmpdir({
      init: async (dir) => {
        const malibuDir = path.join(dir, ".malibu")
        await fs.mkdir(malibuDir, { recursive: true })

        const toolDir = path.join(malibuDir, "tool")
        await fs.mkdir(toolDir, { recursive: true })

        await Bun.write(
          path.join(toolDir, "hello.ts"),
          [
            "export default {",
            "  description: 'hello tool',",
            "  args: {},",
            "  execute: async () => {",
            "    return 'hello world'",
            "  },",
            "}",
            "",
          ].join("\n"),
        )
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const ids = await ToolRegistry.ids()
        expect(ids).toContain("hello")
      },
    })
  })

  test("loads tools from .malibu/tools (plural)", async () => {
    await using tmp = await tmpdir({
      init: async (dir) => {
        const malibuDir = path.join(dir, ".malibu")
        await fs.mkdir(malibuDir, { recursive: true })

        const toolsDir = path.join(malibuDir, "tools")
        await fs.mkdir(toolsDir, { recursive: true })

        await Bun.write(
          path.join(toolsDir, "hello.ts"),
          [
            "export default {",
            "  description: 'hello tool',",
            "  args: {},",
            "  execute: async () => {",
            "    return 'hello world'",
            "  },",
            "}",
            "",
          ].join("\n"),
        )
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const ids = await ToolRegistry.ids()
        expect(ids).toContain("hello")
      },
    })
  })

  test("loads tools with external dependencies without crashing", async () => {
    await using tmp = await tmpdir({
      init: async (dir) => {
        const malibuDir = path.join(dir, ".malibu")
        await fs.mkdir(malibuDir, { recursive: true })

        const toolsDir = path.join(malibuDir, "tools")
        await fs.mkdir(toolsDir, { recursive: true })

        await Bun.write(
          path.join(malibuDir, "package.json"),
          JSON.stringify({
            name: "custom-tools",
            dependencies: {
              "@malibu-ai/plugin": "^0.0.0",
              cowsay: "^1.6.0",
            },
          }),
        )

        await Bun.write(
          path.join(toolsDir, "cowsay.ts"),
          [
            "import { say } from 'cowsay'",
            "export default {",
            "  description: 'tool that imports cowsay at top level',",
            "  args: { text: { type: 'string' } },",
            "  execute: async ({ text }: { text: string }) => {",
            "    return say({ text })",
            "  },",
            "}",
            "",
          ].join("\n"),
        )
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const ids = await ToolRegistry.ids()
        expect(ids).toContain("cowsay")
      },
    })
  })
})
