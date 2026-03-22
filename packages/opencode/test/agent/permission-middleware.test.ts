import { describe, expect, test } from "bun:test"
import { PermissionMiddleware } from "../../src/agent/permission-middleware"

describe("permission-middleware.checkDoomLoop", () => {
  test("allows execution when history is short", () => {
    const history = [{ tool: "bash", input: '{"command":"ls"}' }]
    expect(PermissionMiddleware.checkDoomLoop("bash", '{"command":"ls"}', history)).toBe(true)
  })

  test("allows execution when tools differ", () => {
    const history = [
      { tool: "bash", input: '{"command":"ls"}' },
      { tool: "read", input: '{"file":"a.ts"}' },
      { tool: "bash", input: '{"command":"ls"}' },
    ]
    expect(PermissionMiddleware.checkDoomLoop("bash", '{"command":"ls"}', history)).toBe(true)
  })

  test("blocks execution when same tool+input repeated 3 times", () => {
    const input = '{"command":"ls"}'
    const history = [
      { tool: "bash", input },
      { tool: "bash", input },
      { tool: "bash", input },
    ]
    expect(PermissionMiddleware.checkDoomLoop("bash", input, history)).toBe(false)
  })

  test("allows when last entry differs", () => {
    const input = '{"command":"ls"}'
    const history = [
      { tool: "bash", input },
      { tool: "bash", input },
      { tool: "bash", input: '{"command":"pwd"}' },
    ]
    expect(PermissionMiddleware.checkDoomLoop("bash", '{"command":"pwd"}', history)).toBe(true)
  })

  test("custom threshold parameter works", () => {
    const input = '{"command":"ls"}'
    const history = [
      { tool: "bash", input },
      { tool: "bash", input },
    ]
    // Default threshold (3) should allow
    expect(PermissionMiddleware.checkDoomLoop("bash", input, history)).toBe(true)
    // Custom threshold of 2 should block
    expect(PermissionMiddleware.checkDoomLoop("bash", input, history, 2)).toBe(false)
  })
})
