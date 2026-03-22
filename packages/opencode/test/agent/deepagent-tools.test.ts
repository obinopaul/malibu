/**
 * DeepAgent Built-in Tools Tests
 *
 * Tests DeepAgent's built-in tools (ls, read_file, glob, grep) directly
 * via LocalShellBackend to verify they work correctly and to document
 * their parameter schemas for comparison with Malibu's tools.
 *
 * BackendProtocol methods: lsInfo, read, write, edit, globInfo, grepRaw
 */
import { afterEach, describe, expect, test } from "bun:test"
import path from "path"
import fs from "fs/promises"
import { LocalShellBackend } from "deepagents"
import { tmpdir } from "../fixture/fixture"
import { Instance } from "../../src/project/instance"

afterEach(async () => {
  await Instance.disposeAll()
})

describe("deepagent-tools: LocalShellBackend built-in operations", () => {
  test("ls (lsInfo) lists directory contents", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "hello.ts"), "export const x = 1")
        await fs.mkdir(path.join(dir, "subdir"))
        await fs.writeFile(path.join(dir, "subdir", "nested.ts"), "export const y = 2")
      },
    })

    const backend = new LocalShellBackend({ rootDir: tmp.path })
    await backend.initialize()
    const result = await backend.lsInfo(".")

    expect(result).toBeInstanceOf(Array)
    expect(result.length).toBeGreaterThan(0)
    const paths = result.map((f: any) => f.path)
    expect(paths.some((p: string) => p.includes("hello.ts"))).toBe(true)
    console.log("lsInfo result:", JSON.stringify(result.slice(0, 5), null, 2))
  })

  test("read_file (read) reads file content", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "readme.txt"), "Hello World\nLine 2\nLine 3\n")
      },
    })

    const backend = new LocalShellBackend({ rootDir: tmp.path })
    await backend.initialize()
    const result = await backend.read("readme.txt")

    expect(result).toBeTruthy()
    const content = typeof result === "string" ? result : JSON.stringify(result)
    expect(content).toContain("Hello World")
    console.log("read result:", content.slice(0, 200))
  })

  test("read_file with offset and limit", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        const lines = Array.from({ length: 20 }, (_, i) => `line ${i + 1}`).join("\n")
        await fs.writeFile(path.join(dir, "multiline.txt"), lines)
      },
    })

    const backend = new LocalShellBackend({ rootDir: tmp.path })
    await backend.initialize()
    const result = await backend.read("multiline.txt", 5, 3)

    const content = typeof result === "string" ? result : JSON.stringify(result)
    console.log("read(offset=5, limit=3):", content.slice(0, 200))
    expect(content).toBeTruthy()
  })

  test("glob (globInfo) finds files by pattern", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "app.ts"), "const app = 1")
        await fs.writeFile(path.join(dir, "app.test.ts"), "test()")
        await fs.writeFile(path.join(dir, "readme.md"), "# readme")
      },
    })

    const backend = new LocalShellBackend({ rootDir: tmp.path })
    await backend.initialize()
    const result = await backend.globInfo("*.ts")

    expect(result).toBeInstanceOf(Array)
    const paths = result.map((f: any) => (typeof f === "string" ? f : f.path))
    expect(paths.some((p: string) => p.includes("app.ts"))).toBe(true)
    console.log("globInfo result:", JSON.stringify(paths, null, 2))
  })

  test("grep (grepRaw) searches file contents", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "code.ts"), "const SEARCH_TARGET = 42\nconst other = 1\n")
      },
    })

    const backend = new LocalShellBackend({ rootDir: tmp.path })
    await backend.initialize()
    const result = await backend.grepRaw("SEARCH_TARGET")

    expect(result).toBeInstanceOf(Array)
    if (Array.isArray(result)) {
      expect(result.length).toBeGreaterThan(0)
    }
    console.log("grepRaw result:", JSON.stringify(Array.isArray(result) ? result.slice(0, 3) : result, null, 2))
  })

  test("write_file (write) creates a file", async () => {
    await using tmp = await tmpdir({ git: true })

    const backend = new LocalShellBackend({ rootDir: tmp.path })
    await backend.initialize()
    const result = await backend.write("new-file.txt", "created by deepagent")

    const content = await fs.readFile(path.join(tmp.path, "new-file.txt"), "utf-8")
    expect(content).toBe("created by deepagent")
    console.log("write result:", JSON.stringify(result, null, 2))
  })

  test("edit_file (edit) modifies a file", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "editable.txt"), "before edit")
      },
    })

    const backend = new LocalShellBackend({ rootDir: tmp.path })
    await backend.initialize()
    const result = await backend.edit("editable.txt", "before", "after")

    const content = await fs.readFile(path.join(tmp.path, "editable.txt"), "utf-8")
    expect(content).toBe("after edit")
    console.log("edit result:", JSON.stringify(result, null, 2))
  })
})

describe("deepagent-tools: parallel execution", () => {
  test("multiple reads in parallel via backend", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "a.txt"), "alpha")
        await fs.writeFile(path.join(dir, "b.txt"), "beta")
        await fs.writeFile(path.join(dir, "c.txt"), "gamma")
      },
    })

    const backend = new LocalShellBackend({ rootDir: tmp.path })
    await backend.initialize()

    const results = await Promise.all([
      backend.read("a.txt"),
      backend.read("b.txt"),
      backend.read("c.txt"),
    ])

    const contents = results.map((r) => (typeof r === "string" ? r : JSON.stringify(r)))
    expect(contents[0]).toContain("alpha")
    expect(contents[1]).toContain("beta")
    expect(contents[2]).toContain("gamma")
    console.log("parallel backend reads: all 3 completed")
  })

  test("mixed operations in parallel (ls + read + glob)", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (dir) => {
        await fs.writeFile(path.join(dir, "data.ts"), "const data = true")
      },
    })

    const backend = new LocalShellBackend({ rootDir: tmp.path })
    await backend.initialize()

    const results = await Promise.all([
      backend.lsInfo("."),
      backend.read("data.ts"),
      backend.globInfo("*.ts"),
    ])

    expect(results[0]).toBeInstanceOf(Array)
    const readContent = typeof results[1] === "string" ? results[1] : JSON.stringify(results[1])
    expect(readContent).toContain("data")
    expect(results[2]).toBeInstanceOf(Array)
    console.log("parallel mixed ops: all 3 completed")
  })
})

describe("deepagent-tools: parameter schema comparison", () => {
  test("document DeepAgent vs Malibu parameter naming", () => {
    const comparison = [
      { deepagent: "ls(path?)", opencode: "list(path?, ignore?)", collision: true },
      { deepagent: "read_file(file_path, offset?, limit?)", opencode: "read(filePath, offset?, limit?)", collision: true },
      { deepagent: "write_file(file_path, content?)", opencode: "write(filePath, content)", collision: true },
      { deepagent: "edit_file(file_path, old_string, new_string, replace_all?)", opencode: "edit(filePath, oldString, newString, replaceAll?)", collision: true },
      { deepagent: "glob(pattern, path?)", opencode: "glob(pattern, path?)", collision: true },
      { deepagent: "grep(pattern, path?, glob?)", opencode: "grep(pattern, path?, include?)", collision: true },
      { deepagent: "execute(command)", opencode: "bash(command, timeout?, workdir?, description)", collision: false },
    ]

    console.log("\n=== Parameter Schema Comparison ===")
    for (const c of comparison) {
      const status = c.collision ? "COLLISION (DeepAgent wins)" : "NO COLLISION (both available)"
      console.log(`\n${status}:`)
      console.log(`  DeepAgent: ${c.deepagent}`)
      console.log(`  Malibu:  ${c.opencode}`)
    }

    console.log("\nKey differences:")
    console.log("  - DeepAgent uses snake_case (file_path, old_string)")
    console.log("  - Malibu uses camelCase (filePath, oldString)")
    console.log("  - DeepAgent grep has 'glob' param; Malibu grep has 'include' param")
    console.log("  - DeepAgent 'execute' vs Malibu 'bash' (no collision, both available)")
    console.log("  - Backend protocol: lsInfo, read, write, edit, globInfo, grepRaw")

    expect(true).toBe(true)
  })
})
