/**
 * LangChain ChatModel factory — creates LangChain ChatModel instances
 * for standard providers (OpenAI, Anthropic, Google, etc.)
 */
import { ChatOpenAI } from "@langchain/openai"
import { ChatAnthropic } from "@langchain/anthropic"
import { ChatGoogleGenerativeAI } from "@langchain/google-genai"
import { ChatGroq } from "@langchain/groq"
import { ChatMistralAI } from "@langchain/mistralai"
import { ChatCohere } from "@langchain/cohere"
import { ChatBedrockConverse } from "@langchain/aws"
import type { BaseChatModel } from "@langchain/core/language_models/chat_models"
import { Provider } from "./provider"
import { Auth } from "../auth"
import { Env } from "../env"
import { ProviderTransform } from "./transform"
import { Plugin } from "../plugin"
import { Log } from "../util/log"

const log = Log.create({ service: "langchain-factory" })

export type LangChainModelOptions = {
  temperature?: number
  maxTokens?: number
  streaming?: boolean
  metadata?: Record<string, string>
  sessionID?: string
}

/**
 * Resolves auth credentials for a provider, supporting both API key auth and
 * OAuth/plugin auth (e.g. Codex browser login which injects a custom fetch handler).
 *
 * Resolution order for apiKey:
 *   1. provider.options.apiKey  (set by plugin auth loaders, e.g. OAuth)
 *   2. provider.key             (explicit key from provider config)
 *   3. Auth.get()               (keychain/stored auth, type === "api")
 *   4. env var                  (fallback)
 */
async function resolveProviderAuth(
  model: Provider.Model,
  envKey: string,
  options: LangChainModelOptions = {},
): Promise<{
  apiKey: string | undefined
  baseURL: string | undefined
  customFetch: typeof fetch | undefined
  customHeaders: Record<string, string>
}> {
  // 1. Get the fully-resolved provider (includes plugin auth loaders)
  let providerInfo: Provider.Info | undefined
  try {
    providerInfo = await Provider.getProvider(model.providerID)
  } catch (err) {
    log.warn("failed to resolve provider, falling back to direct auth", {
      provider: model.providerID,
      error: String(err),
    })
  }

  const providerOptions: Record<string, any> = (providerInfo?.options ?? {}) as Record<string, any>

  // 2. Resolve apiKey: provider.options → provider.key → Auth.get() → env var
  let apiKey: string | undefined = providerOptions["apiKey"] as string | undefined
  if (!apiKey && providerInfo?.key) {
    apiKey = providerInfo.key
  }
  if (!apiKey) {
    const auth = await Auth.get(model.providerID)
    apiKey = auth?.type === "api" ? auth.key : undefined
  }
  if (!apiKey) {
    apiKey = Env.get(envKey) ?? undefined
  }

  // 3. Resolve baseURL from provider.options (already variable-substituted by state init)
  const baseURL = providerOptions["baseURL"] as string | undefined

  // 4. Resolve custom fetch from provider.options (plugin auth loaders)
  const customFetch = providerOptions["fetch"] as typeof fetch | undefined

  // 5. Resolve headers: plugin chat.headers hook + model-level headers
  const sessionID = options.metadata?.sessionID ?? options.sessionID ?? ""
  const { headers: pluginHeaders } = await Plugin.trigger(
    "chat.headers",
    { model: model as any, sessionID },
    { headers: {} },
  )

  // Fire chat.params for side-effect parity with original code
  await Plugin.trigger(
    "chat.params",
    { model: model as any, sessionID },
    {},
  )

  // Merge plugin headers + model-level headers
  const customHeaders: Record<string, string> = {
    ...(pluginHeaders ?? {}),
    ...(model.headers ?? {}),
  } as Record<string, string>

  return { apiKey, baseURL, customFetch, customHeaders }
}

/**
 * Creates a ChatOpenAI instance configured for an OpenAI-compatible provider.
 * Used for openrouter, xai, deepinfra, togetherai, cerebras, perplexity.
 */
async function createOpenAICompatible(
  model: Provider.Model,
  options: LangChainModelOptions,
  envKey: string,
  defaultBaseURL: string,
): Promise<BaseChatModel> {
  const resolved = await resolveProviderAuth(model, envKey, options)
  const baseURL = resolved.baseURL ?? defaultBaseURL
  const maxOutputTokens = options.maxTokens ?? ProviderTransform.maxOutputTokens(model)

  return new ChatOpenAI({
    model: model.id,
    apiKey: resolved.apiKey,
    configuration: {
      baseURL,
      fetch: resolved.customFetch,
      defaultHeaders: resolved.customHeaders,
    },
    temperature: options.temperature,
    maxTokens: maxOutputTokens,
    streaming: options.streaming ?? true,
  })
}

type ProviderFactory = (
  model: Provider.Model,
  options: LangChainModelOptions,
) => Promise<BaseChatModel>

const STANDARD_PROVIDERS: Record<string, ProviderFactory> = {
  async anthropic(model, options) {
    const resolved = await resolveProviderAuth(model, "ANTHROPIC_API_KEY", options)
    const maxOutputTokens = options.maxTokens ?? ProviderTransform.maxOutputTokens(model)

    return new ChatAnthropic({
      model: model.id,
      apiKey: resolved.apiKey,
      anthropicApiUrl: resolved.baseURL,
      temperature: options.temperature,
      maxTokens: maxOutputTokens,
      streaming: options.streaming ?? true,
      clientOptions: {
        fetch: resolved.customFetch,
        defaultHeaders: resolved.customHeaders,
      },
    })
  },

  async openai(model, options) {
    const resolved = await resolveProviderAuth(model, "OPENAI_API_KEY", options)
    const maxOutputTokens = options.maxTokens ?? ProviderTransform.maxOutputTokens(model)

    return new ChatOpenAI({
      model: model.id,
      apiKey: resolved.apiKey,
      configuration: {
        baseURL: resolved.baseURL,
        fetch: resolved.customFetch,
        defaultHeaders: resolved.customHeaders,
      },
      temperature: options.temperature,
      maxTokens: maxOutputTokens,
      streaming: options.streaming ?? true,
    })
  },

  async "azure-openai"(model, options) {
    const resolved = await resolveProviderAuth(model, "AZURE_OPENAI_API_KEY", options)
    const endpoint = resolved.baseURL ?? Env.get("AZURE_OPENAI_ENDPOINT")
    if (!endpoint) {
      throw new Error("Azure OpenAI requires a baseURL or AZURE_OPENAI_ENDPOINT environment variable")
    }
    const maxOutputTokens = options.maxTokens ?? ProviderTransform.maxOutputTokens(model)

    return new ChatOpenAI({
      model: model.id,
      apiKey: resolved.apiKey,
      configuration: {
        baseURL: `${endpoint}/openai/deployments/${model.id}`,
        fetch: resolved.customFetch,
        defaultQuery: { "api-version": "2024-08-01-preview" },
        defaultHeaders: {
          ...(resolved.apiKey ? { "api-key": resolved.apiKey } : {}),
          ...resolved.customHeaders,
        },
      },
      temperature: options.temperature,
      maxTokens: maxOutputTokens,
      streaming: options.streaming ?? true,
    })
  },

  async google(model, options) {
    const resolved = await resolveProviderAuth(model, "GOOGLE_API_KEY", options)
    const maxOutputTokens = options.maxTokens ?? ProviderTransform.maxOutputTokens(model)

    return new ChatGoogleGenerativeAI({
      model: model.id,
      apiKey: resolved.apiKey,
      // ChatGoogleGenerativeAI does not support custom fetch or custom headers
      ...(resolved.baseURL ? { baseUrl: resolved.baseURL } : {}),
      temperature: options.temperature,
      maxOutputTokens,
      streaming: options.streaming ?? true,
    })
  },

  async "google-vertex"(model, options) {
    // Vertex uses ADC (Application Default Credentials) — no API key needed.
    // resolveProviderAuth called for plugin hook side effects (chat.headers, chat.params);
    // ChatVertexAI does not accept apiKey/baseURL/customFetch/customHeaders.
    const { ChatVertexAI } = await import("@langchain/google-vertexai")
    const resolved = await resolveProviderAuth(model, "GOOGLE_APPLICATION_CREDENTIALS", options)
    void resolved // side-effect only — Vertex uses ADC, not explicit credentials
    const maxOutputTokens = options.maxTokens ?? ProviderTransform.maxOutputTokens(model)

    return new ChatVertexAI({
      model: model.id,
      temperature: options.temperature,
      maxOutputTokens,
      streaming: options.streaming ?? true,
    })
  },

  async groq(model, options) {
    const resolved = await resolveProviderAuth(model, "GROQ_API_KEY", options)
    const maxOutputTokens = options.maxTokens ?? ProviderTransform.maxOutputTokens(model)

    return new ChatGroq({
      model: model.id,
      apiKey: resolved.apiKey,
      temperature: options.temperature,
      maxTokens: maxOutputTokens,
      streaming: options.streaming ?? true,
    })
  },

  async mistral(model, options) {
    const resolved = await resolveProviderAuth(model, "MISTRAL_API_KEY", options)
    const maxOutputTokens = options.maxTokens ?? ProviderTransform.maxOutputTokens(model)

    return new ChatMistralAI({
      model: model.id,
      apiKey: resolved.apiKey,
      temperature: options.temperature,
      maxTokens: maxOutputTokens,
      streaming: options.streaming ?? true,
    })
  },

  async cohere(model, options) {
    const resolved = await resolveProviderAuth(model, "COHERE_API_KEY", options)

    return new ChatCohere({
      model: model.id,
      apiKey: resolved.apiKey,
      temperature: options.temperature,
      streaming: options.streaming ?? true,
    })
  },

  async "amazon-bedrock"(model, options) {
    // Bedrock uses AWS SigV4 credential chain — resolveProviderAuth called for
    // plugin hook side effects; ChatBedrockConverse uses AWS SDK credential resolution.
    const region = Env.get("AWS_REGION") ?? "us-east-1"
    const resolved = await resolveProviderAuth(model, "AWS_ACCESS_KEY_ID", options)
    void resolved // side-effect only — Bedrock uses AWS credential chain
    const maxOutputTokens = options.maxTokens ?? ProviderTransform.maxOutputTokens(model)

    return new ChatBedrockConverse({
      model: model.id,
      region,
      temperature: options.temperature,
      maxTokens: maxOutputTokens,
    })
  },

  async openrouter(model, options) {
    return createOpenAICompatible(model, options, "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1")
  },

  async xai(model, options) {
    return createOpenAICompatible(model, options, "XAI_API_KEY", "https://api.x.ai/v1")
  },

  async deepinfra(model, options) {
    return createOpenAICompatible(model, options, "DEEPINFRA_API_KEY", "https://api.deepinfra.com/v1/openai")
  },

  async togetherai(model, options) {
    return createOpenAICompatible(model, options, "TOGETHER_API_KEY", "https://api.together.xyz/v1")
  },

  async cerebras(model, options) {
    return createOpenAICompatible(model, options, "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1")
  },

  async perplexity(model, options) {
    return createOpenAICompatible(model, options, "PERPLEXITY_API_KEY", "https://api.perplexity.ai")
  },
}

export namespace LangChainFactory {
  /** Returns true if this provider can be natively created as a LangChain model */
  export function isStandard(providerID: string): boolean {
    return providerID in STANDARD_PROVIDERS
  }

  /** Create a LangChain ChatModel for a standard provider */
  export async function create(
    model: Provider.Model,
    options: LangChainModelOptions = {},
  ): Promise<BaseChatModel> {
    const factory = STANDARD_PROVIDERS[model.providerID]
    if (!factory) {
      throw new Error(`No LangChain factory for provider: ${model.providerID}`)
    }
    log.info("creating langchain model", {
      provider: model.providerID,
      model: model.id,
    })
    try {
      return await factory(model, options)
    } catch (err) {
      throw new Error(
        `Failed to create LangChain model for ${model.providerID}/${model.id}: ${err instanceof Error ? err.message : String(err)}`,
        { cause: err },
      )
    }
  }
}
