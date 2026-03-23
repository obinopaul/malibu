/**
 * createMalibuAgent — custom agent factory that wraps langchain's createAgent.
 *
 * This replaces createDeepAgent from the `deepagents` package. The key difference:
 * NO filesystem middleware is included. Malibu provides its own filesystem
 * tools (read, list, glob, grep, edit, write, bash) via the tool registry,
 * so DeepAgent's built-in filesystem tools are not needed.
 *
 * Middleware assembled (in order):
 * 1. todoListMiddleware — task tracking
 * 2. createSubAgentMiddleware — sub-agent delegation (explore, general)
 * 3. createSummarizationMiddleware — context window management
 * 4. createPatchToolCallsMiddleware — cross-provider tool compat
 * 5. createSkillsMiddleware — skills from .agents/skills/ (conditional)
 * 6. anthropicPromptCachingMiddleware — Anthropic cache (conditional)
 * 7. cacheBreakpointMiddleware — cache breakpoint (conditional, Anthropic)
 * 8. user custom middleware
 */
// tsgo resolves langchain via the "browser" customCondition which lacks agent exports.
// Bun resolves via "input" condition (source .ts) which has all exports. Safe at runtime.
// @ts-expect-error — tsgo browser condition misses agent exports
import { createAgent, createMiddleware, todoListMiddleware, anthropicPromptCachingMiddleware, SystemMessage } from "langchain"
// @ts-expect-error — tsgo browser condition misses AgentMiddleware type
import type { AgentMiddleware } from "langchain"
import type { StructuredTool } from "@langchain/core/tools"
import type { BaseCheckpointSaver } from "@langchain/langgraph-checkpoint"
import {
  createSubAgentMiddleware,
  createSummarizationMiddleware,
  createPatchToolCallsMiddleware,
  createSkillsMiddleware,
  LocalShellBackend,
} from "deepagents"
import type { SubAgent } from "deepagents"

import { createBackgroundSubAgentMiddleware } from "./background-subagents"
import { Log } from "../util/log"

const log = Log.create({ service: "create-agent" })

/**
 * Cache breakpoint middleware — inlined because deepagents doesn't export it.
 * Tags the last system message block with cache_control for Anthropic prompt caching.
 */
function createCacheBreakpointMiddleware() {
  return createMiddleware({
    name: "CacheBreakpointMiddleware",
    wrapModelCall(request: any, handler: any) {
      const existingContent = request.systemMessage?.content
      const existingBlocks =
        typeof existingContent === "string"
          ? [{ type: "text" as const, text: existingContent }]
          : Array.isArray(existingContent)
            ? [...existingContent]
            : []

      if (existingBlocks.length === 0) return handler(request)

      existingBlocks[existingBlocks.length - 1] = {
        ...existingBlocks[existingBlocks.length - 1],
        cache_control: { type: "ephemeral" },
      }

      return handler({
        ...request,
        systemMessage: new SystemMessage({ content: existingBlocks }),
      })
    },
  })
}

export interface CreateMalibuAgentParams {
  /** LangChain ChatModel instance */
  model: any
  /** LangChain StructuredTool[] — Malibu's tools, already converted */
  tools: StructuredTool[]
  /** System prompt string */
  systemPrompt: string
  /** Checkpointer for persistent state */
  checkpointer?: BaseCheckpointSaver | boolean
  /** LocalShellBackend for filesystem access (used by subagents, summarization) */
  backend: LocalShellBackend
  /** Sub-agents (explore, general) */
  subagents?: SubAgent[]
  /** Skill directory paths */
  skills?: string[]
  /** Agent name */
  name?: string
  /** Additional custom middleware (appended last) */
  middleware?: AgentMiddleware[]
  /** Whether to detect Anthropic model for prompt caching */
  isAnthropicModel?: boolean
}

/**
 * Create a Malibu agent using langchain's createAgent directly.
 *
 * Unlike createDeepAgent, this does NOT include filesystem middleware,
 * so no duplicate filesystem tools or conflicting system prompts are injected.
 */
export function createMalibuAgent(params: CreateMalibuAgentParams) {
  const {
    model,
    tools,
    systemPrompt,
    checkpointer,
    backend,
    subagents = [],
    skills,
    name,
    middleware: customMiddleware = [],
    isAnthropicModel = false,
  } = params

  // --- Subagent middleware (passed to createSubAgentMiddleware for subagent-internal use) ---
  // Note: This is a SEPARATE middleware stack from builtInMiddleware.
  // todoListMiddleware() appears here AND in builtInMiddleware intentionally:
  // - Here: gives subagents their own todo tracking
  // - In builtInMiddleware: gives the main agent todo tracking
  const subagentMiddleware: AgentMiddleware[] = [
    todoListMiddleware(),
    createSummarizationMiddleware({ model, backend }),
    createPatchToolCallsMiddleware(),
  ]

  // --- Skills middleware (conditional) ---
  const skillsMiddlewareArray: AgentMiddleware[] =
    skills && skills.length > 0
      ? [createSkillsMiddleware({ backend, sources: skills })]
      : []

  // --- Anthropic caching middleware ---
  const anthropicMiddleware: AgentMiddleware[] = isAnthropicModel
    ? [
        anthropicPromptCachingMiddleware({
          unsupportedModelBehavior: "ignore",
          minMessagesToCache: 1,
        }),
        createCacheBreakpointMiddleware(),
      ]
    : []

  // --- Background sub-agent middleware (async parallel execution) ---
  const { middleware: backgroundMiddleware } = createBackgroundSubAgentMiddleware({
    defaultModel: model,
    defaultTools: tools,
    defaultMiddleware: [...subagentMiddleware, ...anthropicMiddleware],
    generalPurposeAgent: true,
  })

  // --- Built-in middleware (NO filesystem middleware from deepagents) ---
  const builtInMiddleware: AgentMiddleware[] = [
    // 1. Todo list management
    todoListMiddleware(),
    // 2. Sub-agent delegation (explore, general via sync task tool)
    createSubAgentMiddleware({
      defaultModel: model,
      defaultTools: tools,
      defaultMiddleware: [...subagentMiddleware, ...anthropicMiddleware],
      generalPurposeMiddleware: [
        ...subagentMiddleware,
        ...skillsMiddlewareArray,
        ...anthropicMiddleware,
      ],
      subagents,
      generalPurposeAgent: true,
    } as any),
    // 3. Background sub-agents (async parallel via background_task tool)
    backgroundMiddleware,
    // 4. Context summarization
    createSummarizationMiddleware({ model, backend }),
    // 5. Cross-provider tool call compatibility
    createPatchToolCallsMiddleware(),
  ]

  // --- Assemble runtime middleware ---
  const runtimeMiddleware: AgentMiddleware[] = [
    ...builtInMiddleware,
    ...skillsMiddlewareArray,
    ...customMiddleware,
    ...anthropicMiddleware,
  ]

  log.info("createMalibuAgent: assembled middleware", {
    total: runtimeMiddleware.length,
    hasSkills: skillsMiddlewareArray.length > 0,
    isAnthropic: isAnthropicModel,
    subagentCount: subagents.length,
    toolCount: tools.length,
  })

  // --- Create the agent ---
  const agent = createAgent({
    model,
    systemPrompt,
    tools,
    middleware: runtimeMiddleware,
    checkpointer,
    name,
  }).withConfig({
    recursionLimit: 10_000,
    metadata: { ls_integration: "malibu" },
  })

  return agent
}
