import { describe, expect, test, afterEach } from "bun:test"
import { SqliteCheckpointer } from "../../src/agent/checkpointer"
import path from "path"
import os from "os"
import fs from "fs/promises"

let checkpointer: SqliteCheckpointer | undefined

afterEach(() => {
  checkpointer?.close()
  checkpointer = undefined
})

async function tempDb(): Promise<string> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "chk-test-"))
  return path.join(dir, "test-checkpoints.db")
}

describe("checkpointer.SqliteCheckpointer", () => {
  test("creates database and tables", async () => {
    const dbPath = await tempDb()
    checkpointer = new SqliteCheckpointer(dbPath)
    // If constructor didn't throw, tables were created
    expect(checkpointer).toBeDefined()
  })

  test("getTuple returns undefined for non-existent thread", async () => {
    const dbPath = await tempDb()
    checkpointer = new SqliteCheckpointer(dbPath)
    const result = await checkpointer.getTuple({
      configurable: { thread_id: "nonexistent" },
    })
    expect(result).toBeUndefined()
  })

  test("put and getTuple round-trip", async () => {
    const dbPath = await tempDb()
    checkpointer = new SqliteCheckpointer(dbPath)

    const checkpoint = {
      v: 1,
      id: "cp-001",
      ts: new Date().toISOString(),
      channel_values: {},
      channel_versions: {},
      versions_seen: {},
      pending_sends: [],
    }

    const config = {
      configurable: { thread_id: "thread-1", checkpoint_ns: "" },
    }

    await checkpointer.put(config, checkpoint as any, { source: "test" } as any, {})

    const result = await checkpointer.getTuple({
      configurable: { thread_id: "thread-1" },
    })

    expect(result).toBeDefined()
    expect(result!.checkpoint.id).toBe("cp-001")
  })

  test("deleteThread removes checkpoints and writes", async () => {
    const dbPath = await tempDb()
    checkpointer = new SqliteCheckpointer(dbPath)

    const checkpoint = {
      v: 1,
      id: "cp-del",
      ts: new Date().toISOString(),
      channel_values: {},
      channel_versions: {},
      versions_seen: {},
      pending_sends: [],
    }

    await checkpointer.put(
      { configurable: { thread_id: "thread-del", checkpoint_ns: "" } },
      checkpoint as any,
      { source: "test" } as any,
      {},
    )

    // Verify it exists
    let result = await checkpointer.getTuple({
      configurable: { thread_id: "thread-del" },
    })
    expect(result).toBeDefined()

    // Delete
    await checkpointer.deleteThread("thread-del")

    // Verify it's gone
    result = await checkpointer.getTuple({
      configurable: { thread_id: "thread-del" },
    })
    expect(result).toBeUndefined()
  })

  test("list returns checkpoints in descending order", async () => {
    const dbPath = await tempDb()
    checkpointer = new SqliteCheckpointer(dbPath)

    const config = {
      configurable: { thread_id: "thread-list", checkpoint_ns: "" },
    }

    // Insert two checkpoints
    for (const id of ["cp-a", "cp-b"]) {
      const checkpoint = {
        v: 1,
        id,
        ts: new Date().toISOString(),
        channel_values: {},
        channel_versions: {},
        versions_seen: {},
        pending_sends: [],
      }
      await checkpointer.put(config, checkpoint as any, { source: "test" } as any, {})
      // update parent pointer
      config.configurable = { ...config.configurable, checkpoint_id: id } as any
    }

    const results: any[] = []
    for await (const item of checkpointer.list({ configurable: { thread_id: "thread-list" } })) {
      results.push(item)
    }

    expect(results.length).toBe(2)
    // Descending order — cp-b comes first
    expect(results[0].checkpoint.id).toBe("cp-b")
    expect(results[1].checkpoint.id).toBe("cp-a")
  })
})
