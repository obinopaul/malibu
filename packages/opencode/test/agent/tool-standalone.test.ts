/**
 * Standalone Tool Tests — calls Malibu tools directly without the agent.
 *
 * Proves the tools themselves work correctly when called with valid parameters.
 * Tests both individual calls and parallel execution.
 */
import { afterEach, describe, expect, test } from "bun:test"
import path from "path"
import fs from "fs/promises"
import { tmpdir } from "../fixture/fixture"
import { Instance } from "../../src/project/instance"
import { ToolRegistry } from "../../src/tool/registry"
import type { Tool } from "../../src/tool/tool"

afterEach(async () => {
  await Instance.disposeAll()
})

function makeMockContext(overrides?: Partial<Tool.Context>): Tool.Context {
  return {
    sessionID: "test-session" as any,
    messageID: "test-message" as any,
    agent: "test",
    abort: new AbortController().signal,
    messages: [],
    metadata: () => {},
    ask: async () => {},
    ...overrides,
  }
}

describe("tool-standalone: individual tool execution", () => {
  test("list tool lists directory contents", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "alpha.ts"), "export const alpha = true")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const listTool = tools.find((t) => t.id === "list")
        expect(listTool).toBeTruthy()

        const initialized = await listTool!.init({})
        const result = await initialized.execute({ path: tmp.path }, makeMockContext())

        expect(result.output).toContain("alpha.ts")
      },
    })
  })

  test("ls compatibility tool treats '/' as the worktree root", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "root.txt"), "hello")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const lsTool = tools.find((t) => t.id === "ls")
        expect(lsTool).toBeTruthy()

        const initialized = await lsTool!.init({})
        const result = await initialized.execute({ path: "/" }, makeMockContext())

        expect(result.output).toContain("root.txt")
        expect(result.output).toContain(tmp.path)
      },
    })
  })

  test("bash tool executes simple command", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const bashTool = tools.find((t) => t.id === "bash")
        expect(bashTool).toBeTruthy()

        const initialized = await bashTool!.init({})
        const result = await initialized.execute(
          { command: "echo hello", description: "test echo" },
          makeMockContext(),
        )

        expect(result.output).toContain("hello")
        console.log("bash tool output:", result.output.slice(0, 100))
      },
    })
  })

  test("read tool reads a file", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "test.txt"), "line1\nline2\nline3\n")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const readTool = tools.find((t) => t.id === "read")
        expect(readTool).toBeTruthy()

        const initialized = await readTool!.init({})
        const result = await initialized.execute(
          { filePath: path.join(tmp.path, "test.txt") },
          makeMockContext(),
        )

        expect(result.output).toContain("line1")
        expect(result.output).toContain("line2")
        console.log("read tool output:", result.output.slice(0, 200))
      },
    })
  })

  test("read tool falls back to workspace-root-relative paths when cwd is nested", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.mkdir(path.join(dir, "packages", "opencode"), { recursive: true })
        await fs.writeFile(path.join(dir, "packages", "opencode", "package.json"), '{\n  "name": "opencode"\n}\n')
      },
    })

    await Instance.provide({
      directory: path.join(tmp.path, "packages", "opencode"),
      fn: async () => {
        const tools = await ToolRegistry.all()
        const readTool = tools.find((t) => t.id === "read")
        expect(readTool).toBeTruthy()

        const initialized = await readTool!.init({})
        const result = await initialized.execute(
          { filePath: "packages/opencode/package.json" },
          makeMockContext(),
        )

        expect(result.output).toContain('"name": "opencode"')
        expect(result.output).toContain(path.join(tmp.path, "packages", "opencode", "package.json"))
      },
    })
  })

  test("glob tool finds files", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "foo.ts"), "export const foo = 1")
        await fs.writeFile(path.join(dir, "bar.ts"), "export const bar = 2")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const globTool = tools.find((t) => t.id === "glob")
        expect(globTool).toBeTruthy()

        const initialized = await globTool!.init({})
        const result = await initialized.execute(
          { pattern: "*.ts", path: tmp.path },
          makeMockContext(),
        )

        expect(result.output).toContain("foo.ts")
        expect(result.output).toContain("bar.ts")
        console.log("glob tool output:", result.output.slice(0, 200))
      },
    })
  })

  test("list tool falls back to workspace-root-relative paths when cwd is nested", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.mkdir(path.join(dir, "packages", "opencode", "src"), { recursive: true })
        await fs.writeFile(path.join(dir, "packages", "opencode", "src", "index.ts"), "export const ok = true\n")
      },
    })

    await Instance.provide({
      directory: path.join(tmp.path, "packages", "opencode"),
      fn: async () => {
        const tools = await ToolRegistry.all()
        const listTool = tools.find((t) => t.id === "list")
        expect(listTool).toBeTruthy()

        const initialized = await listTool!.init({})
        const result = await initialized.execute(
          { path: "packages/opencode" },
          makeMockContext(),
        )

        expect(result.output).toContain("src/")
        expect(result.output).toContain("index.ts")
        expect(result.output).toContain(path.join(tmp.path, "packages", "opencode"))
      },
    })
  })

  test("grep tool searches file contents", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "search.ts"), "const MAGIC_VALUE = 42\nconst other = 1\n")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const grepTool = tools.find((t) => t.id === "grep")
        expect(grepTool).toBeTruthy()

        const initialized = await grepTool!.init({})
        const result = await initialized.execute(
          { pattern: "MAGIC_VALUE", path: tmp.path },
          makeMockContext(),
        )

        expect(result.output).toContain("MAGIC_VALUE")
        console.log("grep tool output:", result.output.slice(0, 200))
      },
    })
  })

  test("glob and grep fall back to workspace-root-relative paths when cwd is nested", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.mkdir(path.join(dir, "packages", "opencode", "src"), { recursive: true })
        await fs.writeFile(path.join(dir, "packages", "opencode", "src", "index.ts"), "export const TARGET = true\n")
      },
    })

    await Instance.provide({
      directory: path.join(tmp.path, "packages", "opencode"),
      fn: async () => {
        const tools = await ToolRegistry.all()
        const globTool = tools.find((t) => t.id === "glob")
        const grepTool = tools.find((t) => t.id === "grep")
        expect(globTool).toBeTruthy()
        expect(grepTool).toBeTruthy()

        const ctx = makeMockContext()
        const [globInit, grepInit] = await Promise.all([
          globTool!.init({}),
          grepTool!.init({}),
        ])

        const [globResult, grepResult] = await Promise.all([
          globInit.execute({ pattern: "**/*.ts", path: "packages/opencode" }, ctx),
          grepInit.execute({ pattern: "TARGET", path: "packages/opencode" }, ctx),
        ])

        expect(globResult.output).toContain(path.join(tmp.path, "packages", "opencode", "src", "index.ts"))
        expect(grepResult.output).toContain(path.join(tmp.path, "packages", "opencode", "src", "index.ts"))
        expect(grepResult.output).toContain("TARGET")
      },
    })
  })

  test("write tool creates a file", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const writeTool = tools.find((t) => t.id === "write")
        expect(writeTool).toBeTruthy()

        const filePath = path.join(tmp.path, "new-file.txt")
        const initialized = await writeTool!.init({})
        const result = await initialized.execute(
          { filePath, content: "hello from write tool" },
          makeMockContext(),
        )

        const written = await fs.readFile(filePath, "utf-8")
        expect(written).toBe("hello from write tool")
        console.log("write tool output:", result.output.slice(0, 200))
      },
    })
  })

  test("edit tool modifies a file (read first, then edit)", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "edit-me.txt"), "old content here")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const readTool = tools.find((t) => t.id === "read")!
        const editTool = tools.find((t) => t.id === "edit")!
        expect(editTool).toBeTruthy()

        const filePath = path.join(tmp.path, "edit-me.txt")
        const ctx = makeMockContext()

        // Must read before edit (FileTime safety check)
        const readInit = await readTool.init({})
        await readInit.execute({ filePath }, ctx)

        const editInit = await editTool.init({})
        const result = await editInit.execute(
          { filePath, oldString: "old content", newString: "new content" },
          ctx,
        )

        const edited = await fs.readFile(filePath, "utf-8")
        expect(edited).toBe("new content here")
        console.log("edit tool output:", result.output.slice(0, 200))
      },
    })
  })

  test("read_file compatibility tool converts zero-index offsets", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "offset.txt"), "line-1\nline-2\nline-3\n")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const readTool = tools.find((t) => t.id === "read_file")
        expect(readTool).toBeTruthy()

        const initialized = await readTool!.init({})
        const result = await initialized.execute(
          { file_path: "/offset.txt", offset: 1, limit: 1 },
          makeMockContext(),
        )

        expect(result.output).toContain("2: line-2")
        expect(result.output).not.toContain("1: line-1")
      },
    })
  })

  test("grep tool accepts DeepAgent glob alias", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "match.ts"), "const TARGET = true\n")
        await fs.writeFile(path.join(dir, "skip.md"), "TARGET\n")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const grepTool = tools.find((t) => t.id === "grep")
        expect(grepTool).toBeTruthy()

        const initialized = await grepTool!.init({})
        const result = await initialized.execute(
          { pattern: "TARGET", path: "/", glob: "*.ts" },
          makeMockContext(),
        )

        expect(result.output).toContain("match.ts")
        expect(result.output).not.toContain("skip.md")
      },
    })
  })

  test("write_file compatibility tool writes beneath the worktree root", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const writeTool = tools.find((t) => t.id === "write_file")
        expect(writeTool).toBeTruthy()

        const initialized = await writeTool!.init({})
        await initialized.execute(
          { file_path: "/compat.txt", content: "compat write" },
          makeMockContext(),
        )

        const written = await fs.readFile(path.join(tmp.path, "compat.txt"), "utf-8")
        expect(written).toBe("compat write")
      },
    })
  })

  test("edit_file compatibility tool delegates to Malibu edit", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "compat-edit.txt"), "before edit")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const readTool = tools.find((t) => t.id === "read_file")!
        const editTool = tools.find((t) => t.id === "edit_file")!
        const ctx = makeMockContext()

        await (await readTool.init({})).execute({ file_path: "/compat-edit.txt" }, ctx)
        await (await editTool.init({})).execute(
          {
            file_path: "/compat-edit.txt",
            old_string: "before",
            new_string: "after",
          },
          ctx,
        )

        const edited = await fs.readFile(path.join(tmp.path, "compat-edit.txt"), "utf-8")
        expect(edited).toBe("after edit")
      },
    })
  })

  test("execute compatibility tool uses the bash implementation", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const executeTool = tools.find((t) => t.id === "execute")
        expect(executeTool).toBeTruthy()

        const initialized = await executeTool!.init({})
        const result = await initialized.execute({ command: "echo compat-ok" }, makeMockContext())

        expect(result.output).toContain("compat-ok")
        expect(result.title).toBe("Run shell command")
      },
    })
  })
})

describe("tool-standalone: parallel tool execution", () => {
  test("multiple read_file compatibility calls run in parallel", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "a.txt"), "content-a")
        await fs.writeFile(path.join(dir, "b.txt"), "content-b")
        await fs.writeFile(path.join(dir, "c.txt"), "content-c")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const readTool = tools.find((t) => t.id === "read_file")!
        const initialized = await readTool.init({})
        const ctx = makeMockContext()

        const results = await Promise.all([
          initialized.execute({ file_path: "/a.txt" }, ctx),
          initialized.execute({ file_path: "/b.txt" }, ctx),
          initialized.execute({ file_path: "/c.txt" }, ctx),
        ])

        expect(results[0].output).toContain("content-a")
        expect(results[1].output).toContain("content-b")
        expect(results[2].output).toContain("content-c")
      },
    })
  })

  test("multiple reads in parallel", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "a.txt"), "content-a")
        await fs.writeFile(path.join(dir, "b.txt"), "content-b")
        await fs.writeFile(path.join(dir, "c.txt"), "content-c")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const readTool = tools.find((t) => t.id === "read")!
        const initialized = await readTool.init({})
        const ctx = makeMockContext()

        const results = await Promise.all([
          initialized.execute({ filePath: path.join(tmp.path, "a.txt") }, ctx),
          initialized.execute({ filePath: path.join(tmp.path, "b.txt") }, ctx),
          initialized.execute({ filePath: path.join(tmp.path, "c.txt") }, ctx),
        ])

        expect(results[0].output).toContain("content-a")
        expect(results[1].output).toContain("content-b")
        expect(results[2].output).toContain("content-c")
        console.log("parallel reads: all 3 completed successfully")
      },
    })
  })

  test("mixed tools in parallel (glob + grep + bash)", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "find-me.ts"), "export const TARGET = true")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const tools = await ToolRegistry.all()
        const globTool = tools.find((t) => t.id === "glob")!
        const grepTool = tools.find((t) => t.id === "grep")!
        const bashTool = tools.find((t) => t.id === "bash")!

        const [globInit, grepInit, bashInit] = await Promise.all([
          globTool.init({}),
          grepTool.init({}),
          bashTool.init({}),
        ])

        const ctx = makeMockContext()

        const results = await Promise.all([
          globInit.execute({ pattern: "*.ts", path: tmp.path }, ctx),
          grepInit.execute({ pattern: "TARGET", path: tmp.path }, ctx),
          bashInit.execute({ command: "echo parallel-ok", description: "test" }, ctx),
        ])

        expect(results[0].output).toContain("find-me.ts")
        expect(results[1].output).toContain("TARGET")
        expect(results[2].output).toContain("parallel-ok")
        console.log("mixed parallel tools: all 3 completed successfully")
      },
    })
  })
})
