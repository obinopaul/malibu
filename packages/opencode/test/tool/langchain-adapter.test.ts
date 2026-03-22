import { describe, expect, test, beforeEach } from "bun:test"
import {
  toolMetadataStore,
  metadataKey,
  clearSessionMetadata,
} from "../../src/tool/langchain-adapter"

describe("langchain-adapter.toolMetadataStore", () => {
  beforeEach(() => {
    toolMetadataStore.clear()
  })

  test("metadataKey creates scoped key", () => {
    const key = metadataKey("session-1", "call-1")
    expect(key).toBe("session-1:call-1")
  })

  test("set and get metadata", () => {
    const key = metadataKey("s1", "c1")
    toolMetadataStore.set(key, {
      title: "test-tool",
      metadata: { foo: "bar" },
      timestamp: Date.now(),
    })
    const result = toolMetadataStore.get(key)
    expect(result?.title).toBe("test-tool")
    expect(result?.metadata?.foo).toBe("bar")
  })

  test("clearSessionMetadata removes all entries for a session", () => {
    toolMetadataStore.set(metadataKey("s1", "c1"), { title: "a", timestamp: Date.now() })
    toolMetadataStore.set(metadataKey("s1", "c2"), { title: "b", timestamp: Date.now() })
    toolMetadataStore.set(metadataKey("s2", "c3"), { title: "c", timestamp: Date.now() })

    expect(toolMetadataStore.size).toBe(3)
    clearSessionMetadata("s1")
    expect(toolMetadataStore.size).toBe(1)
    expect(toolMetadataStore.has(metadataKey("s2", "c3"))).toBe(true)
  })

  test("clearSessionMetadata is idempotent", () => {
    toolMetadataStore.set(metadataKey("s1", "c1"), { title: "a", timestamp: Date.now() })
    clearSessionMetadata("s1")
    clearSessionMetadata("s1")
    expect(toolMetadataStore.size).toBe(0)
  })
})

describe("langchain-adapter.metadataKey isolation", () => {
  test("different sessions produce different keys", () => {
    const k1 = metadataKey("session-a", "call-1")
    const k2 = metadataKey("session-b", "call-1")
    expect(k1).not.toBe(k2)
  })

  test("different calls in same session produce different keys", () => {
    const k1 = metadataKey("session-a", "call-1")
    const k2 = metadataKey("session-a", "call-2")
    expect(k1).not.toBe(k2)
  })
})
