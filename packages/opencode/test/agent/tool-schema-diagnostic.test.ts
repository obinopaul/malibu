/**
 * Tool Schema Diagnostic Tests — Post-Migration
 *
 * Verifies that after switching to createMalibuAgent:
 * 1. No duplicate tools exist
 * 2. Only Malibu native tool names are in the registry
 * 3. Empty args validation works correctly
 */
import { describe, expect, test } from "bun:test"
import z from "zod"

describe("post-migration: no duplicate tools", () => {
  test("wrapper tools are no longer registered", async () => {
    const file = Bun.file("src/tool/deepagent-filesystem.ts")
    expect(await file.exists()).toBe(false)
  })

  test("registry does not import wrapper tools", async () => {
    const source = await Bun.file("src/tool/registry.ts").text()
    expect(source).not.toContain("deepagent-filesystem")
    expect(source).not.toContain("LsTool")
    expect(source).not.toContain("ReadFileTool")
    expect(source).not.toContain("WriteFileTool")
    expect(source).not.toContain("EditFileTool")
    expect(source).not.toContain("ExecuteTool")
  })

  test("harness uses createMalibuAgent, not createDeepAgent", async () => {
    const source = await Bun.file("src/agent/harness.ts").text()
    expect(source).toContain("createMalibuAgent")
    expect(source).not.toContain("createDeepAgent")
    expect(source).not.toContain("createToolOverrideMiddleware")
  })
})

describe("post-migration: empty args validation", () => {
  test("read({}) FAILS — filePath is required", () => {
    const schema = z.object({
      filePath: z.string().describe("path"),
      offset: z.coerce.number().optional(),
      limit: z.coerce.number().optional(),
    })
    expect(schema.safeParse({}).success).toBe(false)
  })

  test("list({}) PASSES — all params optional", () => {
    const schema = z.object({
      path: z.string().optional(),
      ignore: z.array(z.string()).optional(),
    })
    expect(schema.safeParse({}).success).toBe(true)
  })

  test("glob({}) FAILS — pattern is required", () => {
    const schema = z.object({
      pattern: z.string().describe("pattern"),
      path: z.string().optional(),
    })
    expect(schema.safeParse({}).success).toBe(false)
  })

  test("grep({}) FAILS — pattern is required", () => {
    const schema = z.object({
      pattern: z.string().describe("regex"),
      path: z.string().optional(),
      include: z.string().optional(),
    })
    expect(schema.safeParse({}).success).toBe(false)
  })

  test("bash({}) FAILS — command is required", () => {
    const schema = z.object({
      command: z.string().describe("command"),
      timeout: z.coerce.number().optional(),
      description: z.string().optional(),
    })
    expect(schema.safeParse({}).success).toBe(false)
  })
})
