/**
 * Sub-Agents — defines SubAgent objects for explore and general agents.
 *
 * These SubAgent objects are passed to createMalibuAgent({ subagents: [...] })
 * and automatically wired through the SubAgentMiddleware's `task` tool.
 * When the LLM wants to delegate work, it calls the `task` tool with
 * the sub-agent name and instruction.
 */
import type { SubAgent } from "deepagents"
import { Agent } from "./agent"
import { toLangChainTools, type ToolBridgeContext } from "../tool/langchain-adapter"
import { Provider } from "../provider/provider"
import { UnifiedProvider } from "../provider/unified"
import { Log } from "../util/log"
import type { Tool } from "../tool/tool"
import type { SessionID, MessageID } from "../session/schema"
import type { MessageV2 } from "../session/message-v2"

const log = Log.create({ service: "subagents" })

/** Tools allowed for the explore sub-agent (read-only search) */
const EXPLORE_TOOLS = new Set([
  "bash",
  "webfetch",
  "websearch",
  "codesearch",
])

/** Tools denied for the general sub-agent */
const GENERAL_DENIED_TOOLS = new Set(["todoread", "todowrite"])

/**
 * Tools that duplicate middleware functionality and should NOT be passed
 * as custom tools to createMalibuAgent or sub-agents.
 * - "task" duplicates SubAgentMiddleware's task tool
 * - "todowrite"/"todoread" duplicate TodoListMiddleware
 */
const MIDDLEWARE_ONLY_TOOLS = new Set([
  "task",       // DeepAgent: SubAgentMiddleware task tool
  "todowrite",  // DeepAgent: TodoListMiddleware
  "todoread",   // DeepAgent: TodoListMiddleware
])

export interface SubAgentBuildContext {
  sessionID: SessionID
  messageID: MessageID
  model: Provider.Model
  allTools: Tool.Info[]
  messages: MessageV2.WithParts[]
  abort: AbortSignal
  onMetadata?: (input: { title?: string; metadata?: Record<string, any> }) => void
  onPermission?: (input: any) => Promise<void>
}

/**
 * Build SubAgent objects for the explore and general agents.
 * These are passed to createMalibuAgent({ subagents: [...] }).
 *
 * The SubAgentMiddleware's `task` tool handles dispatch automatically — when
 * the LLM wants to delegate, it calls `task(name="explore", instruction="...")`.
 */
export async function buildSubAgents(
  ctx: SubAgentBuildContext,
): Promise<SubAgent[]> {
  const subagents: SubAgent[] = []

  // Explore sub-agent — limited to read-only search tools
  const exploreAgent = await Agent.get("explore")
  if (exploreAgent) {
    const exploreToolInfos = ctx.allTools.filter(
      (t) => EXPLORE_TOOLS.has(t.id) && !MIDDLEWARE_ONLY_TOOLS.has(t.id),
    )
    const bridge: ToolBridgeContext = {
      sessionID: ctx.sessionID,
      messageID: ctx.messageID,
      agent: "explore",
      abort: ctx.abort,
      messages: ctx.messages,
      onMetadata: ctx.onMetadata,
      onPermission: ctx.onPermission,
    }
    const lcTools = await toLangChainTools(exploreToolInfos, bridge, exploreAgent)

    // Resolve per-agent model override if configured
    let exploreModel: any
    if (exploreAgent.model) {
      try {
        const resolved = await Provider.getModel(
          exploreAgent.model.providerID,
          exploreAgent.model.modelID,
        )
        exploreModel = await UnifiedProvider.create(resolved, {
          temperature: exploreAgent.temperature,
          streaming: true,
        })
      } catch (e: any) {
        log.warn("failed to resolve sub-agent model, falling back to parent", {
          agent: "explore",
          error: e?.message ?? String(e),
        })
      }
    }

    subagents.push({
      name: "explore",
      description:
        exploreAgent.description ??
        "Fast agent for exploring codebases. Use for searching files, reading code, and answering questions about the codebase.",
      systemPrompt:
        exploreAgent.prompt ??
        "You are an explore agent. Search and read code to answer questions about the codebase. Use grep, glob, read, and bash tools to find information efficiently.",
      tools: lcTools,
      ...(exploreModel ? { model: exploreModel } : {}),
    })
  }

  // General sub-agent — full tools minus denied set
  const generalAgent = await Agent.get("general")
  if (generalAgent) {
    const generalToolInfos = ctx.allTools.filter(
      (t) => !GENERAL_DENIED_TOOLS.has(t.id) && !MIDDLEWARE_ONLY_TOOLS.has(t.id),
    )
    const bridge: ToolBridgeContext = {
      sessionID: ctx.sessionID,
      messageID: ctx.messageID,
      agent: "general",
      abort: ctx.abort,
      messages: ctx.messages,
      onMetadata: ctx.onMetadata,
      onPermission: ctx.onPermission,
    }
    const lcTools = await toLangChainTools(generalToolInfos, bridge, generalAgent)

    // Resolve per-agent model override if configured
    let generalModel: any
    if (generalAgent.model) {
      try {
        const resolved = await Provider.getModel(
          generalAgent.model.providerID,
          generalAgent.model.modelID,
        )
        generalModel = await UnifiedProvider.create(resolved, {
          temperature: generalAgent.temperature,
          streaming: true,
        })
      } catch (e: any) {
        log.warn("failed to resolve sub-agent model, falling back to parent", {
          agent: "general",
          error: e?.message ?? String(e),
        })
      }
    }

    subagents.push({
      name: "general",
      description:
        generalAgent.description ??
        "General-purpose agent for researching complex questions and executing multi-step tasks. Use this agent to execute multiple units of work in parallel.",
      systemPrompt:
        generalAgent.prompt ??
        "You are a general-purpose agent. Execute complex, multi-step tasks using the available tools.",
      tools: lcTools,
      ...(generalModel ? { model: generalModel } : {}),
    })
  }

  log.info("built sub-agents", { count: subagents.length })
  return subagents
}
