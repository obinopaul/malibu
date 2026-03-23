/**
 * LangChain Tool Adapter — converts Malibu Tool.Info instances
 * into LangChain DynamicStructuredTool instances.
 *
 * Features:
 * - Preserves existing Zod schemas (LangChain uses Zod natively)
 * - Tool metadata side-channel for title, attachments, metadata
 * - Plugin hook integration (tool.execute.before/after, tool.definition)
 * - Permission integration via existing Permission.ask() + Deferred
 * - Case-insensitive tool name repair for hallucinated names
 */
import { DynamicStructuredTool, ToolInputParsingException } from "@langchain/core/tools"
import { ToolMessage } from "@langchain/core/messages"
import { Tool } from "./tool"
import type { Agent } from "../agent/agent"
import type { MessageV2 } from "../session/message-v2"
import type { Permission } from "../permission"
import type { SessionID, MessageID } from "../session/schema"
import { Plugin } from "../plugin"
import { Log } from "../util/log"
import { PartID } from "../session/schema"

const log = Log.create({ service: "langchain-tool-adapter" })

const METADATA_TTL_MS = 30 * 60 * 1000 // 30 minutes
const METADATA_MAX_SIZE = 1000

/**
 * Side-channel store for tool metadata.
 * Keyed by `${sessionID}:${toolCallId}` to prevent cross-session leaks,
 * stores title/metadata/attachments that LangChain's string-only
 * ToolMessage can't carry.
 */
export const toolMetadataStore = new Map<
  string,
  {
    title?: string
    metadata?: Record<string, any>
    attachments?: any[]
    status?: "completed" | "error"
    timestamp: number
  }
>()

type Meta = NonNullable<ReturnType<typeof toolMetadataStore.get>>

function pruneMetadataStore(): void {
  const now = Date.now()
  for (const [key, entry] of toolMetadataStore) {
    if (now - entry.timestamp > METADATA_TTL_MS) {
      toolMetadataStore.delete(key)
    }
  }
  if (toolMetadataStore.size > METADATA_MAX_SIZE) {
    log.warn("toolMetadataStore exceeds max size", { size: toolMetadataStore.size })
    // Prune oldest entries
    const entries = [...toolMetadataStore.entries()].sort((a, b) => a[1].timestamp - b[1].timestamp)
    const toRemove = entries.slice(0, entries.length - METADATA_MAX_SIZE)
    for (const [key] of toRemove) {
      toolMetadataStore.delete(key)
    }
  }
}

/** Build a scoped key for the metadata store */
export function metadataKey(sessionID: string, toolCallId: string): string {
  return `${sessionID}:${toolCallId}`
}

/** Clean up all metadata entries for a session */
export function clearSessionMetadata(sessionID: string): void {
  for (const key of toolMetadataStore.keys()) {
    if (key.startsWith(`${sessionID}:`)) {
      toolMetadataStore.delete(key)
    }
  }
}

/** Context bridge for tool execution within LangChain agent pipelines */
export interface ToolBridgeContext {
  sessionID: SessionID
  messageID: MessageID
  agent: string
  abort: AbortSignal
  messages: MessageV2.WithParts[]
  permission?: Permission.Ruleset
  onMetadata?: (input: { title?: string; metadata?: Record<string, any> }) => void
  onPermission?: (request: Omit<Permission.Request, "id" | "sessionID" | "tool">) => Promise<void>
}

function makeToolContext(bridge: ToolBridgeContext, callID?: string): Tool.Context {
  return {
    sessionID: bridge.sessionID,
    messageID: bridge.messageID,
    agent: bridge.agent,
    abort: bridge.abort,
    messages: bridge.messages,
    callID,
    metadata: (input) => bridge.onMetadata?.(input),
    ask: async (input) => {
      if (bridge.onPermission) await bridge.onPermission(input)
    },
  }
}

function callID(arg: unknown, config: unknown) {
  const input = arg as any
  if (input?.type === "tool_call" && typeof input.id === "string") return input.id
  const cfg = config as any
  return cfg?.toolCall?.id ?? cfg?.configurable?.tool_call_id ?? cfg?.metadata?.tool_call_id
}

function record(sessionID: string, toolCallId: string, input: Omit<Meta, "timestamp">) {
  pruneMetadataStore()
  toolMetadataStore.set(metadataKey(sessionID, toolCallId), {
    ...input,
    timestamp: Date.now(),
  })
}

function fail(error: unknown) {
  const message = error instanceof Error ? error.message : String(error)
  return `Error: ${message}`
}

/**
 * Convert a single Malibu Tool.Info to a LangChain DynamicStructuredTool.
 *
 * The tool's Zod schema is passed through directly since LangChain
 * uses Zod natively for tool parameter schemas.
 */
export async function toLangChainTool(
  info: Tool.Info,
  bridge: ToolBridgeContext,
  agent?: Agent.Info,
): Promise<DynamicStructuredTool> {
  const initialized = await info.init({ agent })

  // Fire tool.definition hook for plugins that modify tool schemas
  await Plugin.trigger(
    "tool.definition",
    { tool: info.id, sessionID: bridge.sessionID },
    { description: initialized.description, parameters: initialized.parameters },
  )

  const tool = new DynamicStructuredTool({
    name: info.id,
    description: initialized.description,
    schema: initialized.parameters,
    verboseParsingErrors: true,
    func: async (args, _runManager, config) => {
      // Extract the tool_call_id from LangChain config if available
      const toolCallId = (config as any)?.configurable?.tool_call_id
        ?? (config as any)?.metadata?.tool_call_id
        ?? undefined
      const ctx = makeToolContext(bridge, toolCallId)

      try {
        await Plugin.trigger(
          "tool.execute.before",
          {
            tool: info.id,
            sessionID: ctx.sessionID,
            callID: ctx.callID,
          },
          { args },
        )

        const result = await initialized.execute(args, ctx)

        if (toolCallId) {
          record(bridge.sessionID, toolCallId, {
            title: result.title,
            metadata: result.metadata,
            status: "completed",
            attachments: result.attachments?.map((attachment) => ({
              ...attachment,
              id: PartID.ascending(),
              sessionID: ctx.sessionID,
              messageID: bridge.messageID,
            })),
          })
        }

        await Plugin.trigger(
          "tool.execute.after",
          {
            tool: info.id,
            sessionID: ctx.sessionID,
            callID: ctx.callID,
            args,
          },
          result,
        )

        return result.output
      } catch (error: any) {
        if (toolCallId) {
          record(bridge.sessionID, toolCallId, {
            status: "error",
          })
        }
        if (error?.name === "RejectedError" || error?.name === "DeniedError" || error?.name === "CorrectedError") {
          log.info("tool permission denied", { tool: info.id, error: error.message })
          return `Permission denied: ${error.message}`
        }
        log.error("tool execution failed", {
          tool: info.id,
          error: error.message,
        })
        return fail(error)
      }
    },
  })

  const orig = tool.call.bind(tool)
  ;(tool as any).call = async (arg: any, configArg?: any, tags?: string[]) => {
    try {
      return await orig(arg, configArg, tags)
    } catch (error) {
      if (!(error instanceof ToolInputParsingException)) throw error
      const id = callID(arg, configArg)
      if (id) {
        record(bridge.sessionID, id, {
          status: "error",
        })
      }
      const content = fail(error)
      if (!id) return content
      return new ToolMessage({
        tool_call_id: id,
        name: info.id,
        content,
      })
    }
  }

  return tool
}

/**
 * Convert an array of Malibu Tool.Info instances to LangChain tools.
 * Includes a fallback tool for case-insensitive name repair of hallucinated tool names.
 */
export async function toLangChainTools(
  tools: Tool.Info[],
  bridge: ToolBridgeContext,
  agent?: Agent.Info,
): Promise<DynamicStructuredTool[]> {
  const results: DynamicStructuredTool[] = []
  // Build case-insensitive lookup for tool repair
  const toolNameMap = new Map<string, string>()

  for (const info of tools) {
    try {
      const converted = await toLangChainTool(info, bridge, agent)
      results.push(converted)
      toolNameMap.set(info.id.toLowerCase(), info.id)
    } catch (error: any) {
      log.warn("failed to convert tool", {
        tool: info.id,
        error: error.message,
      })
    }
  }

  // Store the lookup map for external use (tool repair in harness)
  _toolNameMap = toolNameMap

  log.info("converted tools", { count: results.length })
  return results
}

/** Case-insensitive tool name map for repair */
let _toolNameMap = new Map<string, string>()

/** Look up a tool name case-insensitively. Returns the correct name or undefined. */
export function repairToolName(name: string): string | undefined {
  return _toolNameMap.get(name.toLowerCase())
}
