/**
 * Tool Integration Audit
 *
 * Verifies that every exported Tool.Info under src/tool has an explicit
 * registry status so tools are no longer "mystery tools".
 */
import { afterEach, describe, expect, test } from "bun:test"
import path from "path"
import fs from "fs/promises"
import { pathToFileURL } from "url"
import { tmpdir } from "../fixture/fixture"
import { Instance } from "../../src/project/instance"
import { ToolRegistry } from "../../src/tool/registry"

const STATUS = {
  apply_patch: "registered",
  bash: "registered",
  batch: "conditional",
  codesearch: "registered",
  edit: "registered",
  glob: "registered",
  grep: "registered",
  invalid: "registered",
  list: "registered",
  lsp: "conditional",
  multiedit: "unexposed",
  plan_exit: "conditional",
  question: "conditional",
  read: "registered",
  skill: "registered",
  task: "registered",
  todoread: "unexposed",
  todowrite: "registered",
  webfetch: "registered",
  websearch: "registered",
  write: "registered",
} as const

const EXTRA_UNEXPOSED = new Set([
  "plan_enter",
])

async function exportedTools() {
  const dir = path.join(import.meta.dir, "../../src/tool")
  const files = await fs.readdir(dir)
  const result = new Set<string>()

  for (const file of files.filter((item) => item.endsWith(".ts"))) {
    const mod = await import(pathToFileURL(path.join(dir, file)).href)
    for (const value of Object.values(mod)) {
      if (!value || typeof value !== "object") continue
      if (!("id" in value) || !("init" in value)) continue
      if (typeof value.id !== "string" || typeof value.init !== "function") continue
      result.add(value.id)
    }
  }

  return [...result].sort()
}

afterEach(async () => {
  await Instance.disposeAll()
})

describe("tool-audit: Malibu vs DeepAgent tool integration", () => {
  test("every exported tool has an explicit registry status", async () => {
    const ids = await exportedTools()
    for (const id of ids) {
      expect(id in STATUS).toBe(true)
    }
    for (const id of EXTRA_UNEXPOSED) {
      expect(id in STATUS || EXTRA_UNEXPOSED.has(id)).toBe(true)
    }
  })

  test("registered tools are present and intentionally unexposed tools stay out", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const allIds = await ToolRegistry.ids()

        for (const [id, state] of Object.entries(STATUS)) {
          if (state === "registered") {
            expect(allIds).toContain(id)
          }
          if (state === "unexposed") {
            expect(allIds).not.toContain(id)
          }
        }

        for (const id of EXTRA_UNEXPOSED) {
          expect(allIds).not.toContain(id)
        }

        expect(allIds).toContain("list")
        expect(allIds).toContain("read")
        expect(allIds).toContain("write")
        expect(allIds).toContain("edit")
        expect(allIds).toContain("bash")
        expect(allIds).not.toContain("ls")
        expect(allIds).not.toContain("read_file")
        expect(allIds).not.toContain("write_file")
        expect(allIds).not.toContain("edit_file")
        expect(allIds).not.toContain("execute")
      },
    })
  })
})
