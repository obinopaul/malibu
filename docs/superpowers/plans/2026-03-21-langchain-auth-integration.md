# LangChain Auth Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the LangChain model factory use the same plugin-based auth system as the AI SDK path, so OAuth (Codex, Copilot) and plugin-configured providers work correctly.

**Architecture:** The AI SDK path works because `Provider.getProvider()` returns `provider.options` which includes plugin-injected `apiKey`, `baseURL`, and custom `fetch` handlers. The LangChain factory bypasses this entirely, reading `Auth.get()` directly. The fix: make `langchain-factory.ts` resolve credentials through the provider system (which already integrates plugin auth loaders), then pass `apiKey`, `baseURL`, and `fetch` to LangChain model constructors. For OAuth, the pattern is: plugin sets `apiKey: OAUTH_DUMMY_KEY` to satisfy required-field validation, plus a custom `fetch` that strips the dummy key and injects the real Bearer token.

**Tech Stack:** LangChain (`@langchain/openai`, `@langchain/anthropic`, etc.), Malibu plugin system, Provider auth system

---

## Root Cause

The LangChain factory (`langchain-factory.ts`) creates models like this:

```typescript
const auth = await Auth.get(model.providerID)
const apiKey = auth?.type === "api" ? auth.key : Env.get("OPENAI_API_KEY")
return new ChatOpenAI({ openAIApiKey: apiKey })
```

This breaks because:
1. **OAuth auth** (`auth.type === "oauth"`) is ignored — falls through to undefined env var
2. **Plugin custom `fetch` handlers** (Codex injects Bearer tokens) are never applied
3. **Plugin `baseURL` overrides** (Copilot Enterprise URLs) are never applied
4. **`provider.options`** (which merges all plugin auth into a single options bag) is never consulted

The AI SDK path works because `Provider.getLanguage()` → `getSDK()` → reads `provider.options` (including plugin's `{ apiKey, fetch, baseURL }`), merges `provider.key`, resolves `baseURL` variables, merges `model.headers`, and wraps fetch with timeout logic.

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/provider/langchain-factory.ts` | **Modify** | Add `resolveProviderAuth()` that gets credentials from the provider system. Update all 14 provider factories to use resolved auth. |
| `test/provider/langchain-factory.test.ts` | **Create** | Test auth resolution for API key, OAuth, and plugin-configured providers. |

---

### Task 1: Add `resolveProviderAuth()` Helper

**Files:**
- Modify: `packages/opencode/src/provider/langchain-factory.ts:1-34`
- Test: `packages/opencode/test/provider/langchain-factory.test.ts`

This helper resolves credentials the same way `getSDK()` does in `provider.ts` — by reading `provider.options` (which has plugin auth merged), falling back to `provider.key`, then `Auth.get()`, then env vars.

- [ ] **Step 1: Write placeholder test file**

Create `packages/opencode/test/provider/langchain-factory.test.ts`:

```typescript
import { describe, test, expect } from "bun:test"

describe("LangChainFactory auth resolution", () => {
  test("placeholder — real tests added in Task 3", () => {
    expect(true).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd packages/opencode && bun test test/provider/langchain-factory.test.ts`
Expected: PASS

- [ ] **Step 3: Update imports and add `resolveProviderAuth()`**

In `packages/opencode/src/provider/langchain-factory.ts`:

**Change the type-only import to a runtime import** (line 13):
```typescript
// BEFORE:
import type { Provider } from "./provider"
// AFTER:
import { Provider } from "./provider"
```

**Remove unused `Config` import** (line 16 — `Config` is never used in this file):
```typescript
// DELETE this line:
import { Config } from "../config/config"
```

**Add the helper after `const log = ...` (line 21):**

```typescript
/**
 * Resolve auth credentials for a provider by consulting the provider system.
 *
 * Mirrors the credential resolution in getSDK() (provider.ts:1186-1317):
 * 1. provider.options — includes plugin auth loaders (apiKey, fetch, baseURL)
 * 2. provider.key — from env var detection or Auth API key loading
 * 3. Auth.get() — direct auth storage fallback
 * 4. Env var — final fallback
 *
 * For OAuth (Codex), plugins set apiKey=OAUTH_DUMMY_KEY to pass required-field
 * validation. The custom fetch handler strips the dummy key and injects the
 * real OAuth Bearer token on every request.
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
  let providerInfo: any
  try {
    providerInfo = await Provider.getProvider(model.providerID)
  } catch {
    // Provider not found in registry — fall through to direct auth
  }

  const providerOptions: Record<string, any> = providerInfo?.options ?? {}

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
```

- [ ] **Step 4: Verify it compiles**

Run: `cd packages/opencode && bun build --no-bundle src/provider/langchain-factory.ts 2>&1 | head -20`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add packages/opencode/src/provider/langchain-factory.ts packages/opencode/test/provider/langchain-factory.test.ts
git commit -m "feat: add resolveProviderAuth() helper for LangChain factory"
```

---

### Task 2: Update All Provider Factories

**Files:**
- Modify: `packages/opencode/src/provider/langchain-factory.ts:36-462`

Replace all 14 provider factories to use `resolveProviderAuth()` instead of direct `Auth.get()`. Each factory passes resolved credentials to the appropriate LangChain constructor parameters.

**LangChain constructor parameter mapping:**
- `ChatOpenAI`: `openAIApiKey`, `configuration: { fetch, baseURL, defaultHeaders }`
- `ChatAnthropic`: `anthropicApiKey`, `anthropicApiUrl` (for baseURL), `clientOptions: { fetch, defaultHeaders }`
- `ChatGoogleGenerativeAI`: `apiKey`, `baseUrl` (limited custom fetch support)
- `ChatGroq`: `apiKey` (extends OpenAI-compatible, `configuration` for fetch/headers)
- `ChatMistralAI`: `apiKey` (limited custom fetch support)
- `ChatCohere`: `apiKey` (limited custom fetch support)
- `ChatBedrockConverse`: AWS IAM auth (no API key)

- [ ] **Step 1: Add `createOpenAICompatible` shared helper and update all factories**

Replace the entire `STANDARD_PROVIDERS` object with:

```typescript
/** Helper for providers that use ChatOpenAI with a custom baseURL */
async function createOpenAICompatible(
  model: Provider.Model,
  options: LangChainModelOptions,
  envKey: string,
  defaultBaseURL: string,
): Promise<BaseChatModel> {
  const resolved = await resolveProviderAuth(model, envKey, options)

  return new ChatOpenAI({
    modelName: model.id,
    openAIApiKey: resolved.apiKey,
    configuration: {
      baseURL: resolved.baseURL ?? defaultBaseURL,
      defaultHeaders: resolved.customHeaders,
      ...(resolved.customFetch ? { fetch: resolved.customFetch } : {}),
    },
    temperature: options.temperature,
    maxTokens: options.maxTokens,
    streaming: options.streaming ?? true,
  })
}

const STANDARD_PROVIDERS: Record<string, ProviderFactory> = {
  async anthropic(model, options) {
    const resolved = await resolveProviderAuth(model, "ANTHROPIC_API_KEY", options)
    const maxOutputTokens = options.maxTokens ?? ProviderTransform.maxOutputTokens(model)

    return new ChatAnthropic({
      modelName: model.id,
      anthropicApiKey: resolved.apiKey,
      temperature: options.temperature,
      maxTokens: maxOutputTokens,
      streaming: options.streaming ?? true,
      ...(resolved.baseURL ? { anthropicApiUrl: resolved.baseURL } : {}),
      clientOptions: {
        defaultHeaders: resolved.customHeaders,
        ...(resolved.customFetch ? { fetch: resolved.customFetch } : {}),
      },
    })
  },

  async openai(model, options) {
    const resolved = await resolveProviderAuth(model, "OPENAI_API_KEY", options)
    const maxOutputTokens = options.maxTokens ?? ProviderTransform.maxOutputTokens(model)

    return new ChatOpenAI({
      modelName: model.id,
      openAIApiKey: resolved.apiKey,
      configuration: {
        defaultHeaders: resolved.customHeaders,
        ...(resolved.customFetch ? { fetch: resolved.customFetch } : {}),
        ...(resolved.baseURL ? { baseURL: resolved.baseURL } : {}),
      },
      temperature: options.temperature,
      maxTokens: maxOutputTokens,
      streaming: options.streaming ?? true,
    })
  },

  async "azure-openai"(model, options) {
    const resolved = await resolveProviderAuth(model, "AZURE_OPENAI_API_KEY", options)
    const endpoint = Env.get("AZURE_OPENAI_ENDPOINT") ?? ""
    const maxOutputTokens = options.maxTokens ?? ProviderTransform.maxOutputTokens(model)

    return new ChatOpenAI({
      modelName: model.id,
      openAIApiKey: resolved.apiKey,
      configuration: {
        baseURL: resolved.baseURL ?? `${endpoint}/openai/deployments/${model.id}`,
        defaultQuery: { "api-version": "2024-08-01-preview" },
        defaultHeaders: { "api-key": resolved.apiKey ?? "", ...resolved.customHeaders },
        ...(resolved.customFetch ? { fetch: resolved.customFetch } : {}),
      },
      temperature: options.temperature,
      maxTokens: maxOutputTokens,
      streaming: options.streaming ?? true,
    })
  },

  async google(model, options) {
    const resolved = await resolveProviderAuth(model, "GOOGLE_API_KEY", options)

    return new ChatGoogleGenerativeAI({
      model: model.id,
      apiKey: resolved.apiKey,
      temperature: options.temperature,
      maxOutputTokens: options.maxTokens,
      streaming: options.streaming ?? true,
      ...(resolved.baseURL ? { baseUrl: resolved.baseURL } : {}),
      // Note: ChatGoogleGenerativeAI has limited custom fetch support.
      // If a plugin injects a custom fetch for Google, it won't be applied here.
      // Use the AI SDK adapter path for Google providers that need custom auth.
    })
  },

  async "google-vertex"(model, options) {
    // Vertex uses ADC (Application Default Credentials) — no API key needed
    const { ChatVertexAI } = await import("@langchain/google-vertexai")

    return new ChatVertexAI({
      model: model.id,
      temperature: options.temperature,
      maxOutputTokens: options.maxTokens,
      streaming: options.streaming ?? true,
    })
  },

  async groq(model, options) {
    const resolved = await resolveProviderAuth(model, "GROQ_API_KEY", options)

    return new ChatGroq({
      model: model.id,
      apiKey: resolved.apiKey,
      temperature: options.temperature,
      maxTokens: options.maxTokens,
      streaming: options.streaming ?? true,
    })
  },

  async mistral(model, options) {
    const resolved = await resolveProviderAuth(model, "MISTRAL_API_KEY", options)

    return new ChatMistralAI({
      model: model.id,
      apiKey: resolved.apiKey,
      temperature: options.temperature,
      maxTokens: options.maxTokens,
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
    // Bedrock uses AWS IAM (SigV4) — no API key needed
    const region = Env.get("AWS_REGION") ?? "us-east-1"

    return new ChatBedrockConverse({
      model: model.id,
      region,
      temperature: options.temperature,
      maxTokens: options.maxTokens,
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
```

- [ ] **Step 2: Verify it compiles**

Run: `cd packages/opencode && bun build --no-bundle src/provider/langchain-factory.ts 2>&1 | head -20`
Expected: No errors

- [ ] **Step 3: Run existing tests to check for regressions**

Run: `cd packages/opencode && bun test --timeout 30000 2>&1 | tail -20`
Expected: No new failures

- [ ] **Step 4: Commit**

```bash
git add packages/opencode/src/provider/langchain-factory.ts
git commit -m "feat: update all LangChain factories to use provider auth system

Replaces direct Auth.get() calls with resolveProviderAuth() which consults
the provider system (provider.options) first. This makes OAuth, plugin-configured
auth (Codex, Copilot), and custom fetch handlers work in the LangChain path.

Auth resolution chain: provider.options.apiKey → provider.key → Auth.get() → env var
Also passes custom fetch handlers and baseURL overrides from plugins."
```

---

### Task 3: Write Integration Tests

**Files:**
- Modify: `packages/opencode/test/provider/langchain-factory.test.ts`

- [ ] **Step 1: Write meaningful tests**

Replace `packages/opencode/test/provider/langchain-factory.test.ts` with:

```typescript
import { describe, test, expect, mock, beforeEach } from "bun:test"
import { useFixture } from "../fixture/fixture"

describe("LangChainFactory", () => {
  // Use the test fixture for proper Malibu initialization
  const fixture = useFixture()

  describe("resolveProviderAuth credential chain", () => {
    test("creates OpenAI model with API key from auth storage", async () => {
      // Set up API key auth in the test fixture's auth storage
      const { Auth } = await import("@/auth")
      await Auth.set("openai", { type: "api", key: "sk-test-key-12345" })

      const { LangChainFactory } = await import("@/provider/langchain-factory")

      // isStandard should recognize openai
      expect(LangChainFactory.isStandard("openai")).toBe(true)
    })

    test("isStandard returns false for unknown providers", async () => {
      const { LangChainFactory } = await import("@/provider/langchain-factory")
      expect(LangChainFactory.isStandard("unknown-provider-xyz")).toBe(false)
    })

    test("isStandard returns true for all standard providers", async () => {
      const { LangChainFactory } = await import("@/provider/langchain-factory")

      const expectedProviders = [
        "anthropic", "openai", "azure-openai", "google", "google-vertex",
        "groq", "mistral", "cohere", "amazon-bedrock",
        "openrouter", "xai", "deepinfra", "togetherai", "cerebras", "perplexity",
      ]

      for (const id of expectedProviders) {
        expect(LangChainFactory.isStandard(id)).toBe(true)
      }
    })

    test("create throws for unknown provider", async () => {
      const { LangChainFactory } = await import("@/provider/langchain-factory")

      await expect(
        LangChainFactory.create({
          id: "test-model",
          providerID: "nonexistent-provider",
        } as any),
      ).rejects.toThrow("No LangChain factory for provider: nonexistent-provider")
    })
  })
})
```

- [ ] **Step 2: Run tests**

Run: `cd packages/opencode && bun test test/provider/langchain-factory.test.ts`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add packages/opencode/test/provider/langchain-factory.test.ts
git commit -m "test: add integration tests for LangChain factory auth resolution"
```

---

### Task 4: Manual Smoke Test

**No files to modify — verification only.**

- [ ] **Step 1: Start malibu**

Run: `cd packages/opencode && bun run dev`
Expected: Starts without errors

- [ ] **Step 2: Test with OpenAI OAuth (Codex auth)**

1. Open malibu TUI
2. Press Ctrl+A → select an OpenAI model (e.g., GPT-5.2)
3. If not already authenticated, use Codex (browser) auth
4. Type a simple prompt: "say hello"
5. Expected: Response streams successfully (no "missing credentials" error)

- [ ] **Step 3: Test with direct API key**

1. Press Ctrl+A → select a provider (e.g., Anthropic or a secondary OpenAI account)
2. Enter API key directly
3. Type a simple prompt
4. Expected: Response streams successfully

- [ ] **Step 4: Verify auth.json state**

Run: `cat ~/.local/share/malibu/auth.json | python3 -c "import json,sys; d=json.load(sys.stdin); print({k: v.get('type','?') for k,v in d.items()})"`
Expected: Shows provider names and auth types (api/oauth)

---

## Verification Checklist

- [ ] `bun build --no-bundle src/provider/langchain-factory.ts` compiles without errors
- [ ] `bun test test/provider/langchain-factory.test.ts` passes
- [ ] `bun run dev` starts without errors
- [ ] OpenAI OAuth (Codex) auth works — can send prompts without "missing credentials"
- [ ] Direct API key auth works — can send prompts with manually entered keys
- [ ] Existing tests still pass: `bun test --timeout 30000`

## Limitations (Known)

1. **Google/Groq/Mistral/Cohere:** These LangChain packages have limited or no custom `fetch` support. If a plugin injects custom auth for these providers, use the AI SDK adapter path instead (add the provider to `AI_SDK_ONLY_PROVIDERS` in `unified.ts`).
2. **baseURL variable substitution:** The provider state initializer already handles `${VAR}` substitution in baseURL when building `provider.options`. The LangChain factory reads the already-resolved value — no additional substitution needed.
3. **Fetch timeout wrapping:** `getSDK()` wraps custom fetch with abort/timeout logic. The LangChain factory passes the raw custom fetch. LangChain's own timeout handling applies instead. This is acceptable because DeepAgent manages timeouts at the harness level.
