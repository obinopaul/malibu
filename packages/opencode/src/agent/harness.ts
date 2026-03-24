/**
 * Harness — uses createMalibuAgent (wrapping langchain's createAgent) as the
 * single agent execution engine.
 *
 * Features:
 * - createMalibuAgent with NO built-in filesystem tools (Malibu's own tools only)
 * - Built-in middleware: TodoList, SubAgents, Summarization, PatchToolCalls, Prompt Caching
 * - Malibu custom tools passed directly — no duplicates, no dedup needed
 * - Sub-agents (explore, general) via langchain's task tool
 * - Skills loaded from .agents/skills/
 * - SQLite-backed checkpointer for persistent state
 * - Delta-based streaming for TUI rendering via Bus events
 * - Doom loop detection, token tracking, error normalization
 */
import { LocalShellBackend } from "deepagents"
import { createMalibuAgent } from "./create-agent"
import {
  HumanMessage,
  AIMessage,
  AIMessageChunk,
  SystemMessage,
  BaseMessage,
  ToolMessage,
} from "@langchain/core/messages"

import { UnifiedProvider } from "../provider/unified"
import { toLangChainTools, type ToolBridgeContext } from "../tool/langchain-adapter"
import { SqliteCheckpointer } from "./checkpointer"
import { PermissionMiddleware } from "./permission-middleware"
import { buildSubAgents } from "./subagents"
import { type Agent } from "./agent"
import { Provider } from "../provider/provider"
import { Instance } from "../project/instance"
import { Skill } from "../skill"
import { Log } from "../util/log"
import { Bus } from "../bus"
import { BusEvent } from "../bus/bus-event"
import type { MessageV2 } from "../session/message-v2"
import type { SessionID, MessageID } from "../session/schema"
import type { Permission } from "../permission"
import type { Tool } from "../tool/tool"
import { canonTool, sameTool } from "../tool/alias"
import z from "zod"

const log = Log.create({ service: "harness" })

/**
 * Tools that duplicate middleware functionality and should NOT be passed
 * as custom tools to createMalibuAgent.
 * - "task" duplicates SubAgentMiddleware's task tool
 * - "todowrite"/"todoread" duplicate TodoListMiddleware
 */
const MIDDLEWARE_ONLY_TOOLS = new Set([
  "task",
  "todowrite",
  "todoread",
])

export namespace Harness {
  /** Events published during harness execution */
  export const Event = {
    TextDelta: BusEvent.define(
      "harness.text.delta",
      z.object({
        sessionID: z.string(),
        text: z.string(),
      }),
    ),
    ToolStart: BusEvent.define(
      "harness.tool.start",
      z.object({
        sessionID: z.string(),
        toolCallId: z.string(),
        tool: z.string(),
        args: z.any(),
      }),
    ),
    ToolEnd: BusEvent.define(
      "harness.tool.end",
      z.object({
        sessionID: z.string(),
        toolCallId: z.string(),
        tool: z.string(),
        output: z.string(),
        args: z.any().optional(),
      }),
    ),
    StepComplete: BusEvent.define(
      "harness.step.complete",
      z.object({
        sessionID: z.string(),
        tokenUsage: z.object({
          prompt: z.number(),
          completion: z.number(),
          reasoning: z.number(),
          cacheRead: z.number(),
          cacheWrite: z.number(),
        }),
      }),
    ),
    PermissionRequired: BusEvent.define(
      "harness.permission.required",
      z.object({
        sessionID: z.string(),
        permission: z.string(),
        patterns: z.array(z.string()),
        metadata: z.any().optional(),
      }),
    ),
    CompactionNeeded: BusEvent.define(
      "harness.compaction.needed",
      z.object({
        sessionID: z.string(),
      }),
    ),
    ReasoningDelta: BusEvent.define(
      "harness.reasoning.delta",
      z.object({
        sessionID: z.string(),
        text: z.string(),
        id: z.string(),
      }),
    ),
    DoomLoop: BusEvent.define(
      "harness.doom-loop",
      z.object({
        sessionID: z.string(),
        tool: z.string(),
        count: z.number(),
      }),
    ),
  }

  export interface Config {
    sessionID: SessionID
    messageID: MessageID
    model: Provider.Model
    agent: Agent.Info
    tools: Tool.Info[]
    messages: MessageV2.WithParts[]
    system: string[]
    abort: AbortSignal
    permission?: Permission.Ruleset
    onPermission?: (request: Omit<Permission.Request, "id" | "sessionID" | "tool">) => Promise<void>
    onMetadata?: (input: { title?: string; metadata?: Record<string, any> }) => void
  }

  export interface TokenUsage {
    prompt: number
    completion: number
    reasoning: number
    cacheRead: number
    cacheWrite: number
  }

  export interface ToolCallResult {
    name: string
    callId: string
    args: any
    output: string
  }

  export type Result = {
    status: "continue" | "stop" | "compact" | "interrupted"
    response?: string
    toolCalls?: ToolCallResult[]
    tokenUsage?: TokenUsage
    reasoning?: string
    interruptValue?: any
  }

  // Shared SQLite-backed checkpointer for persistent session state
  let checkpointer: SqliteCheckpointer | undefined

  function ensureCheckpointer(): SqliteCheckpointer {
    if (!checkpointer) {
      checkpointer = new SqliteCheckpointer()
    }
    return checkpointer
  }

  /** Replace the default checkpointer (for testing) */
  export function setCheckpointer(saver: any) {
    checkpointer = saver
  }

  /** Get the shared checkpointer (lazily initialized) */
  export function getCheckpointer() {
    return ensureCheckpointer()
  }

  /**
   * Build the full createMalibuAgent configuration from a Harness.Config.
   */
  async function buildAgentConfig(config: Config) {
    // 1. Create the LangChain ChatModel via unified provider
    const chatModel = await UnifiedProvider.create(config.model, {
      temperature: config.agent.temperature,
      streaming: true,
      metadata: {
        sessionID: config.sessionID,
        agent: config.agent.name,
      },
    })

      // 2. Convert Malibu tools to LangChain tools
      // Only filter out tools that truly duplicate middleware (task, todowrite, todoread).
      // Filesystem tools and their DeepAgent compatibility names stay enabled.
    const filteredMalibuTools = config.tools.filter(
      (t) => !MIDDLEWARE_ONLY_TOOLS.has(t.id),
    )
    const bridge: ToolBridgeContext = {
      sessionID: config.sessionID,
      messageID: config.messageID,
      agent: config.agent.name,
      abort: config.abort,
      messages: config.messages,
      onMetadata: config.onMetadata,
      onPermission: config.onPermission,
    }
    const langchainTools = await toLangChainTools(filteredMalibuTools, bridge, config.agent)

    // 3. Build the system prompt
    const systemPrompt = config.system.filter(Boolean).join("\n")

    // 4. LocalShellBackend for real filesystem access
    const backend = new LocalShellBackend({ rootDir: Instance.worktree })

    // 5. Build skill paths from .agents/skills/
    let skillPaths: string[] | undefined
    try {
      const skillDirs = await Skill.dirs()
      if (skillDirs.length > 0) {
        skillPaths = skillDirs.map((d: string) => d.endsWith("/") ? d : d + "/")
      }
    } catch {
      // Skills are optional — don't fail if unavailable
    }

    // 6. Build sub-agents (explore, general)
    const subagents = await buildSubAgents({
      sessionID: config.sessionID,
      messageID: config.messageID,
      model: config.model,
      allTools: config.tools,
      messages: config.messages,
      abort: config.abort,
      onMetadata: config.onMetadata,
      onPermission: config.onPermission,
    })

    return {
      chatModel,
      langchainTools,
      systemPrompt,
      backend,
      skillPaths,
      subagents,
    }
  }

  /**
   * Create and run the agent harness for a single turn.
   *
   * Uses createMalibuAgent with:
   * - LocalShellBackend for real filesystem
   * - Sub-agents (explore, general) via built-in task tool
   * - Skills from .agents/skills/
   * - SQLite checkpointer for persistence
   * - streamMode: "messages" for token-level delta streaming
   */
  export async function run(config: Config): Promise<Result> {
    log.info("harness.run", {
      session: config.sessionID,
      agent: config.agent.name,
      model: config.model.id,
    })

    const built = await buildAgentConfig(config)

    const isAnthropicModel = config.model.providerID === "anthropic"
      || config.model.providerID === "anthropic-vertex"
      || config.model.id?.includes("claude")

    let agent = createMalibuAgent({
      model: built.chatModel,
      tools: built.langchainTools,
      systemPrompt: built.systemPrompt,
      checkpointer: ensureCheckpointer(),
      backend: built.backend,
      subagents: built.subagents,
      skills: built.skillPaths,
      name: config.agent.name,
      isAnthropicModel,
    })

    // Map agent.steps to recursionLimit if configured.
    // Each "step" is a model→tool round = 2 graph nodes, so multiply by 2.
    // This replaces the old outer-loop step counting now that the full ReAct
    // loop runs inside a single .stream() call.
    const steps = config.agent.steps
    if (steps && steps < Infinity) {
      agent = agent.withConfig({ recursionLimit: steps * 2 })
    }

    const langchainMessages = convertMessages(config.messages)
    const threadId = `${config.sessionID}-${config.messageID}`

    return streamAgent(agent, { messages: langchainMessages }, threadId, config)
  }

  /**
   * Core stream processing loop for agent execution.
   *
   * Uses streamMode: "messages" for token-level AIMessageChunk streaming.
   * createMalibuAgent wraps createAgent (ReactAgent), so the stream format is standard.
   *
   * Handles:
   * - Token-by-token text rendering in the TUI
   * - Real tool_call_id propagation
   * - Reasoning/thinking content capture
   * - Usage metadata extraction
   * - Doom loop detection
   */
  async function streamAgent(
    agent: ReturnType<typeof createMalibuAgent>,
    input: any,
    threadId: string,
    config: Config,
  ): Promise<Result> {
    const graphConfig = {
      configurable: { thread_id: threadId },
      signal: config.abort,
      metadata: {
        sessionID: config.sessionID,
        agent: config.agent.name,
        model: config.model.id,
      },
    }

    const toolCalls: ToolCallResult[] = []
    const pendingTools = new Map<string, { name: string; args: string; started: boolean }>()
    // Map chunk index → pendingTools id, so subsequent tool_call_chunks (which lack
    // an `id` field and only carry `index` + `args`) can be correlated to the right entry.
    const chunkIndexToId = new Map<number, string>()
    // Index: tool name → ordered list of pending IDs, used to detect double-tracking.
    // When the same tool call appears in both tool_call_chunks (ID "0") and
    // tool_calls (ID "call_abc"), we re-key to the authoritative ID.
    // Uses an ordered array so parallel calls to the same tool (e.g., two "read" calls)
    // can be matched by position (FIFO).
    const pendingNameToIds = new Map<string, string[]>()
    const toolCallHistory: Array<{ tool: string; input: string }> = []
    let response = ""

    /** Track a tool name → ID association (maintains arrival order) */
    function trackPendingName(name: string, id: string) {
      const key = canonTool(name)
      let ids = pendingNameToIds.get(key)
      if (!ids) { ids = []; pendingNameToIds.set(key, ids) }
      if (!ids.includes(id)) ids.push(id)
    }
    /** Remove a tool name → ID association */
    function untrackPendingName(name: string, id: string) {
      const key = canonTool(name)
      const ids = pendingNameToIds.get(key)
      if (ids) {
        const idx = ids.indexOf(id)
        if (idx !== -1) ids.splice(idx, 1)
        if (ids.length === 0) pendingNameToIds.delete(key)
      }
    }
    /**
     * Find a pending entry for a tool name that was tracked under a DIFFERENT ID.
     * For a single pending call, returns that ID directly.
     * For parallel calls (multiple IDs for the same name), returns the OLDEST
     * candidate (FIFO order) so that position-based matching works correctly.
     * This handles GPT-5.4's double-ID pattern even with parallel same-name calls.
     */
    function findRekeyCandidate(name: string, newId: string): string | undefined {
      const ids = pendingNameToIds.get(canonTool(name))
      if (!ids) return undefined
      // Filter to IDs that aren't the new one and still exist in pendingTools
      const candidates = ids.filter((id) => {
        if (id === newId || !pendingTools.has(id)) return false
        return sameTool(pendingTools.get(id)?.name, name)
      })
      // Return the oldest candidate (first in arrival order) for FIFO matching
      return candidates.length > 0 ? candidates[0] : undefined
    }
    let reasoning = ""
    let tokenUsage: TokenUsage = { prompt: 0, completion: 0, reasoning: 0, cacheRead: 0, cacheWrite: 0 }

    try {
      const stream = await agent.stream(input, {
        ...graphConfig,
        streamMode: "messages",
      })

      for await (const event of stream) {
        if (config.abort.aborted) break

        // streamMode: "messages" yields [message, metadata] tuples
        const [msg] = Array.isArray(event) ? event : [event]

        if (msg instanceof AIMessageChunk) {
          // --- Text delta ---
          if (typeof msg.content === "string" && msg.content) {
            response += msg.content
            Bus.publish(Event.TextDelta, {
              sessionID: config.sessionID,
              text: msg.content,
            })
          } else if (Array.isArray(msg.content)) {
            for (const part of msg.content) {
              const p = part as any
              if (typeof p === "string") {
                response += p
                Bus.publish(Event.TextDelta, {
                  sessionID: config.sessionID,
                  text: p,
                })
              } else if (p.type === "text" && p.text) {
                response += p.text
                Bus.publish(Event.TextDelta, {
                  sessionID: config.sessionID,
                  text: String(p.text),
                })
              } else if (p.type === "thinking" && p.thinking) {
                // Anthropic extended thinking
                reasoning += p.thinking
                Bus.publish(Event.ReasoningDelta, {
                  sessionID: config.sessionID,
                  text: String(p.thinking),
                  id: p.id ?? "default",
                })
              } else if (p.type === "reasoning" && p.reasoning) {
                // OpenAI reasoning models (o1, o3, GPT-5.x)
                reasoning += p.reasoning
                Bus.publish(Event.ReasoningDelta, {
                  sessionID: config.sessionID,
                  text: String(p.reasoning),
                  id: p.id ?? "openai-reasoning",
                })
              }
            }
          }

          // --- Tool call chunks (streaming deltas) ---
          // LangChain sends tool_call_chunks with `id` only on the first chunk.
          // Subsequent delta chunks carry `index` + `args` but NO `id`.
          // We use chunkIndexToId to correlate deltas back to the right pending entry.
          for (const tcChunk of msg.tool_call_chunks ?? []) {
            const id = tcChunk.id
            const index = (tcChunk as any).index as number | undefined

            if (id) {
              // Initial chunk — has id (and usually name)
              if (!pendingTools.has(id)) {
                pendingTools.set(id, { name: tcChunk.name ?? "", args: tcChunk.args ?? "", started: false })
                if (tcChunk.name) trackPendingName(tcChunk.name, id)
                log.info("tool_call_chunk:new", {
                  id,
                  name: tcChunk.name,
                  hasArgs: !!tcChunk.args,
                  argsLen: tcChunk.args?.length ?? 0,
                  pendingCount: pendingTools.size,
                })
              } else {
                const pending = pendingTools.get(id)!
                if (tcChunk.name && !pending.name) {
                  pending.name = tcChunk.name
                  trackPendingName(tcChunk.name, id)
                }
                pending.args += tcChunk.args ?? ""
              }
              // Track index→id so subsequent chunks without id can be correlated
              if (index !== undefined && index !== null) {
                chunkIndexToId.set(index, id)
              }
            } else if (index !== undefined && index !== null) {
              // Delta chunk — no id, use index to find the right pending entry
              const mappedId = chunkIndexToId.get(index)
              if (mappedId && pendingTools.has(mappedId)) {
                pendingTools.get(mappedId)!.args += tcChunk.args ?? ""
              }
            }
          }

          // --- Complete tool_calls (some providers send both chunks AND complete calls) ---
          // GPT-5.4 via ChatOpenAI sends tool_call_chunks with IDs like "0","1"
          // AND tool_calls with IDs like "call_abc123" on the SAME AIMessageChunk.
          // The ToolMessage will use the tool_calls ID, so we re-key to that.
          for (const tc of msg.tool_calls ?? []) {
            const id = tc.id ?? tc.name
            // If already tracked by tool_call_chunks with same ID, update args
            // from the complete tool_calls (chunks may have empty/partial args)
            if (pendingTools.has(id)) {
              const existing = pendingTools.get(id)!
              if (tc.args && Object.keys(tc.args).length > 0) {
                const existingArgs = existing.args ? (() => { try { return JSON.parse(existing.args) } catch { return {} } })() : {}
                if (Object.keys(existingArgs).length === 0) {
                  existing.args = JSON.stringify(tc.args)
                  log.info("tool_call:args_upgraded", {
                    id,
                    name: tc.name,
                    argsKeys: Object.keys(tc.args),
                  })
                }
              }
              continue
            }

            // Check if this is the same tool call already tracked under a different ID
            // (from tool_call_chunks). If so, re-key to the authoritative ID.
            const existingId = tc.name ? findRekeyCandidate(tc.name, id) : undefined
            if (existingId) {
              const pending = pendingTools.get(existingId)
              pendingTools.delete(existingId)
              const toolName = pending?.name || tc.name
              if (toolName) untrackPendingName(toolName, existingId)
              pendingTools.set(id, { name: toolName ?? "", args: JSON.stringify(tc.args), started: false })
              if (toolName) trackPendingName(toolName, id)
              log.info("tool_call:rekey", {
                oldId: existingId,
                newId: id,
                name: toolName,
                pendingCount: pendingTools.size,
              })
              if (pending?.started) {
                await Bus.publish(Event.ToolEnd, {
                  sessionID: config.sessionID,
                  toolCallId: existingId,
                  tool: toolName ?? "unknown",
                  output: "(re-keyed)",
                })
              }
              await Bus.publish(Event.ToolStart, {
                sessionID: config.sessionID,
                toolCallId: id,
                tool: toolName ?? "unknown",
                args: tc.args,
              })
              pendingTools.get(id)!.started = true
              continue
            }

            log.info("tool_call:complete", {
              id,
              name: tc.name,
              argsKeys: Object.keys(tc.args ?? {}),
              pendingCount: pendingTools.size,
            })
            pendingTools.set(id, { name: tc.name, args: JSON.stringify(tc.args), started: false })
            if (tc.name) trackPendingName(tc.name, id)
            await Bus.publish(Event.ToolStart, {
              sessionID: config.sessionID,
              toolCallId: id,
              tool: tc.name,
              args: tc.args,
            })
            pendingTools.get(id)!.started = true
          }

          // --- Usage metadata (emitted on final chunk) ---
          const usageMeta = (msg as any).usage_metadata
          if (usageMeta) {
            tokenUsage.prompt += usageMeta.input_tokens ?? 0
            tokenUsage.completion += usageMeta.output_tokens ?? 0
            tokenUsage.cacheRead += usageMeta.input_token_details?.cache_read ?? 0
            tokenUsage.cacheWrite += usageMeta.input_token_details?.cache_creation ?? 0
            tokenUsage.reasoning +=
              usageMeta.output_token_details?.reasoning_tokens
              ?? usageMeta.output_token_details?.reasoning
              ?? 0
          }

          // Check for reasoning in additional_kwargs
          const addKwargs = (msg as any).additional_kwargs
          // Anthropic extended thinking
          if (addKwargs?.thinking) {
            const thinkingText = typeof addKwargs.thinking === "string"
              ? addKwargs.thinking
              : addKwargs.thinking?.thinking ?? ""
            if (thinkingText && !reasoning.includes(thinkingText)) {
              reasoning += thinkingText
              Bus.publish(Event.ReasoningDelta, {
                sessionID: config.sessionID,
                text: thinkingText,
                id: "extended-thinking",
              })
            }
          }
          // OpenAI reasoning (Responses API stores reasoning item in additional_kwargs)
          if (addKwargs?.reasoning) {
            const r = addKwargs.reasoning
            const reasoningText = typeof r === "string"
              ? r
              : r?.summary?.map((s: any) => s.text).filter(Boolean).join("") ?? ""
            if (reasoningText && !reasoning.includes(reasoningText)) {
              reasoning += reasoningText
              Bus.publish(Event.ReasoningDelta, {
                sessionID: config.sessionID,
                text: reasoningText,
                id: r?.id ?? "openai-reasoning",
              })
            }
          }
        } else if (msg instanceof ToolMessage) {
          let toolCallId = (msg as any).tool_call_id ?? ""
          const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)
          let pending = pendingTools.get(toolCallId)

          // Fallback: if ID lookup fails, match by tool name to handle ID mismatches
          // between tool_call_chunks and ToolMessage (e.g., different ID formats across providers).
          // CRITICAL: Must also re-key harness-processor's toolcalls dict by publishing
          // ToolEnd for the old ID and ToolStart for the new ID, otherwise the old entry
          // remains in toolcalls and becomes an orphan.
          if (!pending && msg.name) {
            for (const [id, p] of pendingTools) {
              if (sameTool(p.name, msg.name)) {
                log.warn("tool_call_id mismatch, matched by name", {
                  expected: id,
                  received: toolCallId,
                  tool: msg.name,
                  pendingKeys: [...pendingTools.keys()],
                })
                pending = p
                pendingTools.delete(id)
                untrackPendingName(p.name, id)
                pendingTools.set(toolCallId, pending)
                trackPendingName(p.name, toolCallId)

                // Re-key harness-processor: close old ID, open new ID
                if (pending.started) {
                  const toolName = pending.name || msg.name || "unknown"
                  await Bus.publish(Event.ToolEnd, {
                    sessionID: config.sessionID,
                    toolCallId: id,
                    tool: toolName,
                    output: "(re-keyed)",
                  })
                  await Bus.publish(Event.ToolStart, {
                    sessionID: config.sessionID,
                    toolCallId: toolCallId,
                    tool: toolName,
                    args: pending.args ? (() => { try { return JSON.parse(pending.args) } catch { return {} } })() : {},
                  })
                }
                break
              }
            }
          }

          log.info("tool_message:received", {
            toolCallId,
            name: msg.name,
            matched: !!pending,
            pendingCount: pendingTools.size,
            contentLen: content.length,
          })

          let parsedArgs: any = {}
          if (pending?.args) {
            try {
              parsedArgs = JSON.parse(pending.args)
            } catch {
              parsedArgs = pending?.args ?? {}
            }
          }

          log.info("tool_message:parsedArgs", {
            toolCallId,
            name: msg.name,
            pendingArgsRaw: pending?.args?.slice(0, 200),
            parsedArgsKeys: Object.keys(parsedArgs),
            pendingStarted: pending?.started,
          })

          const toolName = pending?.name ?? msg.name ?? "unknown"
          if (pending && !pending.started) {
            await Bus.publish(Event.ToolStart, {
              sessionID: config.sessionID,
              toolCallId,
              tool: toolName,
              args: parsedArgs,
            })
            pending.started = true
          }

          toolCalls.push({
            name: toolName,
            callId: toolCallId,
            args: parsedArgs,
            output: content,
          })

          // Always clean up pendingTools BEFORE publishing ToolEnd and doom loop check.
          // This prevents orphans when doom loop triggers an early return.
          pendingTools.delete(toolCallId)
          if (toolName) untrackPendingName(toolName, toolCallId)

          await Bus.publish(Event.ToolEnd, {
            sessionID: config.sessionID,
            toolCallId,
            tool: toolName,
            output: content,
            args: parsedArgs,
          })

          // Doom loop detection
          const serializedArgs = JSON.stringify(parsedArgs)
          toolCallHistory.push({ tool: toolName, input: serializedArgs })
          if (!PermissionMiddleware.checkDoomLoop(toolName, serializedArgs, toolCallHistory)) {
            log.warn("doom loop detected", { tool: toolName, count: toolCallHistory.length })
            Bus.publish(Event.DoomLoop, {
              sessionID: config.sessionID,
              tool: toolName,
              count: toolCallHistory.length,
            })
            return {
              status: "stop" as const,
              response: response + `\n\n[Doom loop detected: tool "${toolName}" called repeatedly with identical arguments. Stopping to prevent infinite loop.]`,
              toolCalls,
              tokenUsage,
              reasoning: reasoning || undefined,
            }
          }
        } else if (msg instanceof AIMessage) {
          if (typeof msg.content === "string" && msg.content) {
            response += msg.content
            Bus.publish(Event.TextDelta, {
              sessionID: config.sessionID,
              text: msg.content,
            })
          }

          const usageMeta = (msg as any).usage_metadata
          if (usageMeta) {
            tokenUsage.prompt += usageMeta.input_tokens ?? 0
            tokenUsage.completion += usageMeta.output_tokens ?? 0
            tokenUsage.cacheRead += usageMeta.input_token_details?.cache_read ?? 0
            tokenUsage.cacheWrite += usageMeta.input_token_details?.cache_creation ?? 0
            tokenUsage.reasoning +=
              usageMeta.output_token_details?.reasoning_tokens
              ?? usageMeta.output_token_details?.reasoning
              ?? 0
          }

          for (const tc of msg.tool_calls ?? []) {
            const id = tc.id ?? tc.name
            // Same upgrade logic as AIMessageChunk handler
            if (pendingTools.has(id)) {
              const existing = pendingTools.get(id)!
              if (tc.args && Object.keys(tc.args).length > 0) {
                const existingArgs = existing.args ? (() => { try { return JSON.parse(existing.args) } catch { return {} } })() : {}
                if (Object.keys(existingArgs).length === 0) {
                  existing.args = JSON.stringify(tc.args)
                  log.info("tool_call:args_upgraded(AIMessage)", { id, name: tc.name })
                }
              }
              continue
            }

            // Same re-key logic as AIMessageChunk handler
            const existingId = tc.name ? findRekeyCandidate(tc.name, id) : undefined
            if (existingId) {
              const pending = pendingTools.get(existingId)
              pendingTools.delete(existingId)
              const toolName = pending?.name || tc.name
              if (toolName) untrackPendingName(toolName, existingId)
              pendingTools.set(id, { name: toolName ?? "", args: JSON.stringify(tc.args), started: false })
              if (toolName) trackPendingName(toolName, id)
              log.info("tool_call:rekey(AIMessage)", {
                oldId: existingId,
                newId: id,
                name: toolName,
              })
              if (pending?.started) {
                await Bus.publish(Event.ToolEnd, {
                  sessionID: config.sessionID,
                  toolCallId: existingId,
                  tool: toolName ?? "unknown",
                  output: "(re-keyed)",
                })
              }
              await Bus.publish(Event.ToolStart, {
                sessionID: config.sessionID,
                toolCallId: id,
                tool: toolName ?? "unknown",
                args: tc.args,
              })
              pendingTools.get(id)!.started = true
              continue
            }

            pendingTools.set(id, { name: tc.name, args: JSON.stringify(tc.args), started: false })
            if (tc.name) trackPendingName(tc.name, id)
            await Bus.publish(Event.ToolStart, {
              sessionID: config.sessionID,
              toolCallId: id,
              tool: tc.name,
              args: tc.args,
            })
            pendingTools.get(id)!.started = true
          }
        }
      }

      // Resolve any pending tools that never got a ToolMessage
      // (DeepAgent middleware tools like write_file/edit_file return Command objects
      // whose embedded ToolMessages may not stream as standalone events)
      // Must await each publish so the async ToolEnd subscriber in harness-processor
      // finishes cleaning up before Harness.run() returns and the orphan check runs.
      if (pendingTools.size > 0) {
        log.info("synthetic:cleanup", {
          pendingCount: pendingTools.size,
          pendingTools: [...pendingTools.entries()].map(([id, p]) => ({ id, name: p.name })),
        })
      }
      for (const [id, pending] of pendingTools) {
        const toolName = pending.name || "unknown"
        let parsedArgs: any = {}
        try { parsedArgs = JSON.parse(pending.args) } catch { parsedArgs = {} }
        if (!pending.started) {
          await Bus.publish(Event.ToolStart, {
            sessionID: config.sessionID,
            toolCallId: id,
            tool: toolName,
            args: parsedArgs,
          })
          pending.started = true
        }
        const output = [
          "Tool execution completed during synthetic cleanup.",
          `tool: ${toolName}`,
          `call_id: ${id}`,
          `args: ${JSON.stringify(parsedArgs)}`,
          "reason: tool started but only resolved in synthetic cleanup",
        ].join("\n")
        log.warn("tool started but only resolved in synthetic cleanup", {
          callId: id,
          tool: toolName,
          args: parsedArgs,
        })
        toolCalls.push({
          name: toolName,
          callId: id,
          args: parsedArgs,
          output,
        })
        await Bus.publish(Event.ToolEnd, {
          sessionID: config.sessionID,
          toolCallId: id,
          tool: toolName,
          output,
        })
        pendingTools.delete(id)
      }

      Bus.publish(Event.StepComplete, {
        sessionID: config.sessionID,
        tokenUsage,
      })

      // createAgent (ReactAgent) runs the full ReAct loop internally within
      // a single .stream() call — model → tools → model → ... → final text.
      // When the stream ends naturally, the agent has completed its reasoning.
      // Always return "stop" to avoid redundant re-invocations from the outer
      // session loop (which was designed for single-step processing).
      // The recursionLimit: 10_000 in create-agent.ts handles loop continuation.
      return {
        status: "stop" as const,
        response,
        toolCalls,
        tokenUsage,
        reasoning: reasoning || undefined,
      }
    } catch (error: any) {
      // Resolve pending tools before returning so they don't become orphaned
      // in harness-processor. This is critical for error paths where the stream
      // breaks mid-execution (e.g., network errors, tool failures, aborts).
      if (pendingTools.size > 0) {
        log.warn("resolving pending tools after error", {
          errorName: error.name,
          pendingCount: pendingTools.size,
          pendingTools: [...pendingTools.entries()].map(([id, p]) => ({ id, name: p.name })),
        })
        for (const [id, pending] of pendingTools) {
          const toolName = pending.name || "unknown"
          let parsedArgs: any = {}
          try { parsedArgs = JSON.parse(pending.args) } catch { parsedArgs = {} }
          if (!pending.started) {
            await Bus.publish(Event.ToolStart, {
              sessionID: config.sessionID,
              toolCallId: id,
              tool: toolName,
              args: parsedArgs,
            })
            pending.started = true
          }
          const output = [
            "Tool execution aborted before completion.",
            `tool: ${toolName}`,
            `call_id: ${id}`,
            `args: ${JSON.stringify(parsedArgs)}`,
            "reason: stream error while tool was pending",
            `error: ${error.message ?? error.name ?? "unknown error"}`,
          ].join("\n")
          toolCalls.push({
            name: toolName,
            callId: id,
            args: parsedArgs,
            output,
          })
          await Bus.publish(Event.ToolEnd, {
            sessionID: config.sessionID,
            toolCallId: id,
            tool: toolName,
            output,
          })
          pendingTools.delete(id)
        }
      }

      // Handle interrupts (safety net — permissions use Effect Deferred, not LangGraph interrupts)
      if (error.name === "GraphInterrupt") {
        log.warn("unexpected GraphInterrupt received", { session: config.sessionID, value: error.value })
        return {
          status: "interrupted",
          interruptValue: error.value,
          response,
          toolCalls,
          tokenUsage,
        }
      }

      // Handle abort
      if (config.abort.aborted || error.name === "AbortError") {
        return { status: "stop", response, toolCalls, tokenUsage }
      }

      log.error("harness error", { error: error.message, status: error.status ?? error.statusCode })

      const normalized = normalizeLangChainError(error)
      throw normalized
    }
  }

  /** Convert Malibu messages to LangChain BaseMessage format */
  export function convertMessages(messages: MessageV2.WithParts[]): BaseMessage[] {
    const result: BaseMessage[] = []

    for (const msg of messages) {
      const role = msg.info.role
      const parts = msg.parts as any[]

      if (role === "user") {
        const contentParts: any[] = []

        for (const p of parts ?? []) {
          if (p.type === "text" && (p.content || p.text)) {
            contentParts.push({ type: "text", text: p.content ?? p.text })
          } else if (p.type === "file" && p.mime && p.data) {
            if (p.mime.startsWith("image/")) {
              contentParts.push({
                type: "image_url",
                image_url: { url: `data:${p.mime};base64,${p.data}` },
              })
            }
          }
        }

        if (contentParts.length === 1 && contentParts[0]?.type === "text") {
          result.push(new HumanMessage(contentParts[0].text))
        } else if (contentParts.length > 0) {
          result.push(new HumanMessage({ content: contentParts }))
        }
      } else if (role === "assistant") {
        const summaryParts = parts?.filter((p) => p.type === "summary") ?? []
        for (const sp of summaryParts) {
          const summaryText = sp.content ?? sp.text ?? sp.summary
          if (summaryText) {
            result.push(new SystemMessage(`[Session Summary]\n${summaryText}`))
          }
        }

        const textParts = parts
          ?.filter((p) => p.type === "text")
          .map((p) => p.content ?? p.text)
          .join("")

        const toolCallParts = parts?.filter((p) => p.type === "tool") ?? []

        if (toolCallParts.length > 0) {
          result.push(
            new AIMessage({
              content: textParts || "",
              tool_calls: toolCallParts.map((tc: any) => ({
                id: tc.callID ?? tc.id,
                name: tc.tool,
                args: tc.state?.input ?? {},
              })),
            }),
          )
          // Always create a ToolMessage for every tool call to prevent dangling
          // AIMessage tool_calls that violate the API contract and cause errors.
          for (const tc of toolCallParts) {
            const status = tc.state?.status
            let content: string
            if (status === "completed") {
              content = tc.state?.output ?? ""
            } else if (status === "error") {
              content = tc.state?.error ?? "Tool execution failed"
            } else {
              // Handle "running", "pending", undefined, or any other status
              content = tc.state?.output ?? tc.state?.error
                ?? `Tool execution incomplete (status: ${status ?? "unknown"})`
            }
            result.push(
              new ToolMessage({
                tool_call_id: tc.callID ?? tc.id,
                name: tc.tool,
                content,
              }),
            )
          }
        } else if (textParts) {
          result.push(new AIMessage(textParts))
        }
      }
    }

    return result
  }

  /**
   * Normalize LangChain errors to a format that MessageV2.fromError()
   * and ProviderError can classify correctly.
   */
  function normalizeLangChainError(error: any): Error {
    if (error.statusCode || error.status) {
      const code = error.statusCode ?? error.status
      const msg = error.message ?? "Unknown error"
      const normalized = new Error(msg) as any
      normalized.statusCode = code
      normalized.responseBody = error.responseBody ?? error.body ?? ""
      normalized.isRetryable = code === 429 || code >= 500
      normalized.name = error.name ?? "APICallError"
      return normalized
    }

    if (error.error?.status || error.cause?.status) {
      const inner = error.error ?? error.cause
      const code = inner.status ?? inner.statusCode
      const msg = inner.message ?? error.message ?? "Unknown error"
      const normalized = new Error(msg) as any
      normalized.statusCode = code
      normalized.responseBody = JSON.stringify(inner.body ?? inner.error ?? "")
      normalized.isRetryable = code === 429 || code >= 500
      normalized.name = "APICallError"
      return normalized
    }

    return error
  }
}
