import { describe, expect, test } from "bun:test"
import { UnifiedProvider } from "../../src/provider/unified"

describe("unified-provider.getModelType", () => {
  test("routes anthropic to langchain", () => {
    expect(UnifiedProvider.getModelType("anthropic")).toBe("langchain")
  })

  test("routes openai to langchain", () => {
    expect(UnifiedProvider.getModelType("openai")).toBe("langchain")
  })

  test("routes google to langchain", () => {
    expect(UnifiedProvider.getModelType("google")).toBe("langchain")
  })

  test("routes groq to langchain", () => {
    expect(UnifiedProvider.getModelType("groq")).toBe("langchain")
  })

  test("routes mistral to langchain", () => {
    expect(UnifiedProvider.getModelType("mistral")).toBe("langchain")
  })

  test("routes amazon-bedrock to langchain", () => {
    expect(UnifiedProvider.getModelType("amazon-bedrock")).toBe("langchain")
  })

  test("routes openrouter to langchain", () => {
    expect(UnifiedProvider.getModelType("openrouter")).toBe("langchain")
  })

  test("routes github-copilot to ai-sdk-adapter", () => {
    expect(UnifiedProvider.getModelType("github-copilot")).toBe("ai-sdk-adapter")
  })

  test("routes gitlab to ai-sdk-adapter", () => {
    expect(UnifiedProvider.getModelType("gitlab")).toBe("ai-sdk-adapter")
  })

  test("routes malibu to ai-sdk-adapter", () => {
    expect(UnifiedProvider.getModelType("malibu")).toBe("ai-sdk-adapter")
  })

  test("routes unknown providers to ai-sdk-adapter", () => {
    expect(UnifiedProvider.getModelType("some-custom-provider")).toBe("ai-sdk-adapter")
  })
})

describe("unified-provider.isSupported", () => {
  test("standard providers are supported", () => {
    expect(UnifiedProvider.isSupported("anthropic")).toBe(true)
    expect(UnifiedProvider.isSupported("openai")).toBe(true)
  })

  test("AI SDK providers are supported", () => {
    expect(UnifiedProvider.isSupported("github-copilot")).toBe(true)
    expect(UnifiedProvider.isSupported("gitlab")).toBe(true)
  })

  test("unknown providers are not supported", () => {
    expect(UnifiedProvider.isSupported("random-provider")).toBe(false)
  })
})

describe("unified-provider.supportedProviders", () => {
  test("returns all supported provider IDs", () => {
    const providers = UnifiedProvider.supportedProviders()
    expect(providers).toContain("anthropic")
    expect(providers).toContain("openai")
    expect(providers).toContain("google")
    expect(providers).toContain("github-copilot")
    expect(providers).toContain("malibu")
    expect(providers.length).toBeGreaterThan(10)
  })
})
