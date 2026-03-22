/**
 * Unified Provider — routes model creation to either LangChain native
 * providers or the AI SDK adapter based on provider type.
 *
 * Standard providers (OpenAI, Anthropic, Google, etc.) use LangChain natively.
 * Custom providers (Copilot, GitLab, SAP) use the AI SDK adapter wrapper.
 */
import type { BaseChatModel } from "@langchain/core/language_models/chat_models"
import { LangChainFactory, type LangChainModelOptions } from "./langchain-factory"
import { AISdkChatModel, type AISdkAdapterInput } from "./ai-sdk-adapter"
import { Provider } from "./provider"
import { Log } from "../util/log"

const log = Log.create({ service: "unified-provider" })

/** Providers that should use the AI SDK adapter (no native LangChain support) */
const AI_SDK_ONLY_PROVIDERS = new Set([
  "github-copilot",
  "gitlab",
  "malibu",
  "azure-cognitive-services",
  "ai-gateway",
  "vercel",
])

export namespace UnifiedProvider {
  export type ModelType = "langchain" | "ai-sdk-adapter"

  export function getModelType(providerID: string): ModelType {
    if (AI_SDK_ONLY_PROVIDERS.has(providerID)) return "ai-sdk-adapter"
    if (LangChainFactory.isStandard(providerID)) return "langchain"
    // Fall back to AI SDK adapter for unknown providers
    return "ai-sdk-adapter"
  }

  /**
   * Create a LangChain-compatible ChatModel for any provider.
   * Routes to native LangChain or AI SDK adapter as appropriate.
   */
  export async function create(
    model: Provider.Model,
    options: LangChainModelOptions = {},
  ): Promise<BaseChatModel> {
    const type = getModelType(model.providerID)
    log.info("creating unified model", {
      provider: model.providerID,
      model: model.id,
      type,
    })

    if (type === "langchain") {
      return LangChainFactory.create(model, options)
    }

    // AI SDK adapter path — get the Vercel AI SDK language model
    const language = await Provider.getLanguage(model)
    return new AISdkChatModel({
      model: language,
      providerID: model.providerID,
      modelID: model.id,
      temperature: options.temperature,
      maxTokens: options.maxTokens,
    })
  }

  /** Check if a provider is supported */
  export function isSupported(providerID: string): boolean {
    return LangChainFactory.isStandard(providerID) || AI_SDK_ONLY_PROVIDERS.has(providerID)
  }

  /** Get all supported provider IDs */
  export function supportedProviders(): string[] {
    const standard = [
      "anthropic",
      "openai",
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
    ]
    return [...standard, ...AI_SDK_ONLY_PROVIDERS]
  }
}
