/**
 * Tests for createMalibuAgent — verifies middleware assembly
 * and that NO filesystem middleware is included.
 */
import { describe, expect, test } from "bun:test"

describe("createMalibuAgent", () => {
  test("does not include createFilesystemMiddleware", async () => {
    const source = await Bun.file("src/agent/create-agent.ts").text()
    expect(source).not.toContain("createFilesystemMiddleware")
    expect(source).not.toContain("FilesystemMiddleware")
    expect(source).toContain("todoListMiddleware")
    expect(source).toContain("createSubAgentMiddleware")
    expect(source).toContain("createSummarizationMiddleware")
    expect(source).toContain("createPatchToolCallsMiddleware")
  })

  test("exports createMalibuAgent function", async () => {
    const mod = await import("../../src/agent/create-agent")
    expect(typeof mod.createMalibuAgent).toBe("function")
  })
})
