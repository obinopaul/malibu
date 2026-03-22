import { describe, expect, test } from "bun:test"
import { LangChainFactory } from "../../src/provider/langchain-factory"

describe("LangChainFactory.isStandard", () => {
  const KNOWN_PROVIDERS = [
    "anthropic",
    "openai",
    "azure-openai",
    "google",
    "google-vertex",
    "groq",
    "mistral",
    "cohere",
    "amazon-bedrock",
    "openrouter",
    "xai",
    "deepinfra",
    "togetherai",
    "cerebras",
    "perplexity",
  ] as const

  test.each([...KNOWN_PROVIDERS])("returns true for known provider: %s", (providerID) => {
    expect(LangChainFactory.isStandard(providerID as string)).toBe(true)
  })

  test("returns false for unknown provider", () => {
    expect(LangChainFactory.isStandard("unknown")).toBe(false)
  })

  test("returns false for copilot", () => {
    expect(LangChainFactory.isStandard("copilot")).toBe(false)
  })

  test("returns false for gitlab", () => {
    expect(LangChainFactory.isStandard("gitlab")).toBe(false)
  })

  test("returns false for empty string", () => {
    expect(LangChainFactory.isStandard("")).toBe(false)
  })
})

describe("LangChainFactory.create", () => {
  test("throws for unknown provider", async () => {
    const fakeModel = {
      providerID: "unknown-provider",
      id: "some-model",
    } as any

    await expect(LangChainFactory.create(fakeModel)).rejects.toThrow(
      "No LangChain factory for provider: unknown-provider",
    )
  })

  test("throws for copilot provider", async () => {
    const fakeModel = {
      providerID: "copilot",
      id: "some-model",
    } as any

    await expect(LangChainFactory.create(fakeModel)).rejects.toThrow(
      "No LangChain factory for provider: copilot",
    )
  })

  test("throws for gitlab provider", async () => {
    const fakeModel = {
      providerID: "gitlab",
      id: "some-model",
    } as any

    await expect(LangChainFactory.create(fakeModel)).rejects.toThrow(
      "No LangChain factory for provider: gitlab",
    )
  })
})
