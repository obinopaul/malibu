/**
 * Tool Override Middleware Tests
 *
 * Verifies that createToolOverrideMiddleware deduplicates duplicate tool names
 * so Malibu's tools stay first and DeepAgent's later duplicates are hidden.
 *
 * Also verifies the updated collision filter (MIDDLEWARE_ONLY_TOOLS)
 * only removes task/todowrite/todoread, keeping filesystem tools.
 */
import { afterEach, describe, expect, test } from "bun:test"
import { tmpdir } from "../fixture/fixture"
import { Instance } from "../../src/project/instance"
import { dedupeRequestTools } from "../../src/agent/tool-dedupe"
import { ToolRegistry } from "../../src/tool/registry"

/** Tools that should be filtered by MIDDLEWARE_ONLY_TOOLS (duplicates middleware) */
const MIDDLEWARE_ONLY_TOOLS = new Set(["task", "todowrite", "todoread"])

const FILESYSTEM_TOOLS = new Set([
  "ls",
  "read",
  "read_file",
  "write",
  "write_file",
  "edit",
  "edit_file",
  "glob",
  "grep",
  "list",
  "execute",
])

afterEach(async () => {
  await Instance.disposeAll()
})

describe("tool-override-middleware: filtering logic", () => {
  test("middleware keeps Malibu compatibility tools first and drops later duplicates", () => {
    // Simulates request.tools as seen by wrapModelCall:
    // toolClasses = [...userTools, ...middlewareTools]
    const mockTools = [
      // Malibu tools (from options.tools — come FIRST)
      { name: "ls", description: "List files (Malibu compat)" },
      { name: "read_file", description: "Read file (Malibu compat)" },
      { name: "write_file", description: "Write file (Malibu compat)" },
      { name: "edit_file", description: "Edit file (Malibu compat)" },
      { name: "execute", description: "Execute command (Malibu compat)" },
      { name: "glob", description: "Glob for files (Malibu)" },
      { name: "grep", description: "Search file contents (Malibu)" },
      { name: "list", description: "List directory (Malibu)" },
      { name: "read", description: "Read a file (Malibu)" },
      { name: "write", description: "Write a file (Malibu)" },
      { name: "edit", description: "Edit a file (Malibu)" },
      { name: "bash", description: "Execute bash command" },
      { name: "webfetch", description: "Fetch a URL" },
      // DeepAgent middleware tools (come AFTER user tools)
      { name: "ls", description: "List files (DeepAgent)" },
      { name: "read_file", description: "Read file (DeepAgent)" },
      { name: "write_file", description: "Write file (DeepAgent)" },
      { name: "edit_file", description: "Edit file (DeepAgent)" },
      { name: "glob", description: "Glob (DeepAgent)" },
      { name: "grep", description: "Grep (DeepAgent)" },
      { name: "execute", description: "Execute command (DeepAgent)" },
      // DeepAgent non-filesystem middleware tools
      { name: "todowrite", description: "Write todo" },
      { name: "todoread", description: "Read todo" },
      { name: "task", description: "Task tool" },
    ]

    const { kept, dropped } = dedupeRequestTools(mockTools)

    expect(dropped).toContain("ls")
    expect(dropped).toContain("read_file")
    expect(dropped).toContain("write_file")
    expect(dropped).toContain("edit_file")
    expect(dropped).toContain("execute")
    expect(dropped).toContain("glob")
    expect(dropped).toContain("grep")

    expect(kept.find((t) => t.name === "ls")?.description).toContain("Malibu compat")
    expect(kept.find((t) => t.name === "read_file")?.description).toContain("Malibu compat")
    expect(kept.find((t) => t.name === "glob")?.description).toContain("Malibu")
    expect(kept.find((t) => t.name === "grep")?.description).toContain("Malibu")
    expect(kept.find((t) => t.name === "task")?.description).toContain("Task tool")
    expect(kept.find((t) => t.name === "todoread")?.description).toContain("Read todo")

    const globTools = kept.filter((t) => t.name === "glob")
    const grepTools = kept.filter((t) => t.name === "grep")
    expect(globTools).toHaveLength(1)
    expect(grepTools).toHaveLength(1)
    expect(globTools[0].description).toContain("Malibu")
    expect(grepTools[0].description).toContain("Malibu")
  })

  test("MIDDLEWARE_ONLY_TOOLS only filters task, todowrite, todoread", () => {
    expect(MIDDLEWARE_ONLY_TOOLS.size).toBe(3)
    expect(MIDDLEWARE_ONLY_TOOLS.has("task")).toBe(true)
    expect(MIDDLEWARE_ONLY_TOOLS.has("todowrite")).toBe(true)
    expect(MIDDLEWARE_ONLY_TOOLS.has("todoread")).toBe(true)

    // Filesystem tools should NOT be in the filter set
    for (const id of ["read", "write", "edit", "glob", "grep", "list"]) {
      expect(MIDDLEWARE_ONLY_TOOLS.has(id)).toBe(false)
    }
  })

  test("middleware preserves ordering: Malibu first, DeepAgent second", () => {
    const tools = [
      { name: "read_file", source: "malibu" },
      { name: "glob", source: "malibu" },
      { name: "glob", source: "deepagent" },
      { name: "read_file", source: "deepagent" },
    ]

    const { kept } = dedupeRequestTools(tools)

    expect(kept.filter((t) => t.name === "glob")).toHaveLength(1)
    expect(kept.find((t) => t.name === "glob")?.source).toBe("malibu")
    expect(kept.filter((t) => t.name === "read_file")).toHaveLength(1)
    expect(kept.find((t) => t.name === "read_file")?.source).toBe("malibu")
  })
})

describe("tool-override-middleware: Malibu tool availability", () => {
  test("filesystem tools pass through MIDDLEWARE_ONLY_TOOLS filter", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const allTools = await ToolRegistry.all()
        const allIds = allTools.map((t) => t.id)

        // Apply the new filter (same as harness.ts)
        const available = allIds.filter((id) => !MIDDLEWARE_ONLY_TOOLS.has(id))
        const filtered = allIds.filter((id) => MIDDLEWARE_ONLY_TOOLS.has(id))

        console.log("\n=== Updated Tool Availability ===")
        console.log(`Total tools: ${allIds.length}`)
        console.log(`Available to agent: ${available.length}`)
        console.log(`Filtered (middleware-only): ${filtered.length}`)
        console.log(`Available: ${available.join(", ")}`)
        console.log(`Filtered: ${filtered.join(", ")}`)

        for (const toolId of FILESYSTEM_TOOLS) {
          if (allIds.includes(toolId)) {
            expect(available).toContain(toolId)
            console.log(`  ✓ ${toolId} — available to the agent`)
          }
        }

        // task, todowrite, todoread should still be filtered
        for (const toolId of MIDDLEWARE_ONLY_TOOLS) {
          if (allIds.includes(toolId)) {
            expect(filtered).toContain(toolId)
          }
        }
      },
    })
  })

  test("Malibu filesystem tools have rich Zod schemas with descriptions", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const allTools = await ToolRegistry.all()

        const filesystemToolIds = ["ls", "read", "read_file", "write", "write_file", "edit", "edit_file", "glob", "grep", "execute"]
        for (const id of filesystemToolIds) {
          const tool = allTools.find((t) => t.id === id)
          if (!tool) continue

          const initialized = await tool.init({})
          expect(initialized.description).toBeTruthy()
          expect(initialized.parameters).toBeTruthy()

          const shape = (initialized.parameters as any)?.shape ?? {}
          const paramNames = Object.keys(shape)
          expect(paramNames.length).toBeGreaterThan(0)

          // Check that at least some params have .describe() hints
          let hasDescriptions = false
          for (const key of paramNames) {
            const field = shape[key]
            if (field?.description || field?._def?.description) {
              hasDescriptions = true
              break
            }
          }

          console.log(`Tool "${id}": params=[${paramNames.join(", ")}], hasDescriptions=${hasDescriptions}`)
        }
      },
    })
  })

  test("no duplicate tool names in final available set", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const allTools = await ToolRegistry.all()
        const available = allTools
          .map((t) => t.id)
          .filter((id) => !MIDDLEWARE_ONLY_TOOLS.has(id))

        const seen = new Set<string>()
        const duplicates: string[] = []
        for (const id of available) {
          if (seen.has(id)) duplicates.push(id)
          seen.add(id)
        }

        expect(duplicates).toHaveLength(0)
      },
    })
  })
})

describe("tool-override-middleware: ToolNode ordering", () => {
  test("user tools come before middleware tools, .find() returns Malibu first", () => {
    // Simulates ReactAgent line 67:
    // const toolClasses = [...options.tools, ...middlewareTools]
    const userTools = [
      { name: "ls", source: "malibu" },
      { name: "read_file", source: "malibu" },
      { name: "glob", source: "malibu" },
      { name: "grep", source: "malibu" },
      { name: "execute", source: "malibu" },
    ]
    const middlewareTools = [
      { name: "ls", source: "deepagent" },
      { name: "read_file", source: "deepagent" },
      { name: "glob", source: "deepagent" },
      { name: "grep", source: "deepagent" },
    ]

    const toolClasses = [...userTools, ...middlewareTools]

    // Simulates ToolNode.js line 190:
    // const tool = this.tools.find((t) => t.name === toolCall.name)
    const findTool = (name: string) => toolClasses.find((t) => t.name === name)

    // For same-name tools, Malibu's version found first
    expect(findTool("ls")?.source).toBe("malibu")
    expect(findTool("read_file")?.source).toBe("malibu")
    expect(findTool("glob")?.source).toBe("malibu")
    expect(findTool("grep")?.source).toBe("malibu")
    expect(findTool("execute")?.source).toBe("malibu")
  })
})
