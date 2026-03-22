/**
 * Harness-Based Processor — bridges the LangGraph harness output back
 * to Malibu's session state management (MessageV2, parts, snapshots).
 *
 * Primary session processor using the DeepAgent harness (createDeepAgent).
 *
 * Now supports:
 * - Incremental text deltas for TUI streaming
 * - Real tool_call_id from LangGraph (not synthetic)
 * - Cost tracking via Session.getUsage()
 * - Error handling with retry logic (matching SessionRetry)
 * - Reasoning part capture
 * - Plugin hooks (tool.execute.before/after)
 * - Tool metadata side-channel
 */
import { MessageV2 } from "./message-v2"
import { Log } from "@/util/log"
import { Session } from "."
import { Harness } from "@/agent/harness"
import { Snapshot } from "@/snapshot"
import { SessionSummary } from "./summary"
import { SessionCompaction } from "./compaction"
import { SessionRetry } from "./retry"
import { SessionStatus } from "./status"
import { Plugin } from "@/plugin"
import { Bus } from "@/bus"
import { PartID } from "./schema"
import type { SessionID } from "./schema"
import type { Provider } from "@/provider/provider"
import type { Agent } from "@/agent/agent"
import type { Permission } from "@/permission"
import type { Tool } from "@/tool/tool"
import { sameTool } from "@/tool/alias"
import { toolMetadataStore, metadataKey, clearSessionMetadata } from "@/tool/langchain-adapter"

const log = Log.create({ service: "harness-processor" })

/** Human-readable titles for DeepAgent built-in tool names */
const DEEPAGENT_TOOL_TITLES: Record<string, string> = {
  read_file: "Read",
  write_file: "Write",
  edit_file: "Edit",
  ls: "List",
  glob: "Glob",
  grep: "Grep",
  task: "Task",
  write_todos: "TodoWrite",
}

export namespace HarnessProcessor {
  export type Info = Awaited<ReturnType<typeof create>>
  export type Result = "continue" | "stop" | "compact"

  export function create(input: {
    assistantMessage: MessageV2.Assistant
    sessionID: SessionID
    model: Provider.Model
    abort: AbortSignal
  }) {
    let needsCompaction = false
    let attempt = 0

    const result = {
      get message() {
        return input.assistantMessage
      },
      async process(streamInput: {
        agent: Agent.Info
        permission?: Permission.Ruleset
        system: string[]
        messages: MessageV2.WithParts[]
        tools: Tool.Info[]
        abort: AbortSignal
        onPermission?: (request: any) => Promise<void>
      }): Promise<Result> {
        log.info("process via harness")
        needsCompaction = false

        // Retry loop matching processor.ts pattern
        while (true) {
          try {
            return await processOnce(input, streamInput)
          } catch (e: any) {
            log.error("harness process error", {
              error: e,
              stack: JSON.stringify(e.stack),
            })

            const error = MessageV2.fromError(e, { providerID: input.model.providerID })

            if (MessageV2.ContextOverflowError.isInstance(error)) {
              needsCompaction = true
              Bus.publish(Session.Event.Error, {
                sessionID: input.sessionID,
                error,
              })
              return "compact"
            }

            const retry = SessionRetry.retryable(error)
            if (retry !== undefined) {
              attempt++
              const delay = SessionRetry.delay(attempt, MessageV2.APIError.isInstance(error) ? error : undefined)
              SessionStatus.set(input.sessionID, {
                type: "retry",
                attempt,
                message: retry,
                next: Date.now() + delay,
              })
              await SessionRetry.sleep(delay, input.abort).catch(() => {})
              continue
            }

            // Non-retryable error
            input.assistantMessage.error = error
            Bus.publish(Session.Event.Error, {
              sessionID: input.assistantMessage.sessionID,
              error: input.assistantMessage.error,
            })
            SessionStatus.set(input.sessionID, { type: "idle" })
            return "stop"
          }
        }
      },
    }
    return result
  }

  /** Single processing attempt — extracted for retry loop */
  async function processOnce(
    input: {
      assistantMessage: MessageV2.Assistant
      sessionID: SessionID
      model: Provider.Model
      abort: AbortSignal
    },
    streamInput: {
      agent: Agent.Info
      permission?: Permission.Ruleset
      system: string[]
      messages: MessageV2.WithParts[]
      tools: Tool.Info[]
      abort: AbortSignal
      onPermission?: (request: any) => Promise<void>
    },
  ): Promise<"continue" | "stop" | "compact"> {
    SessionStatus.set(input.sessionID, { type: "busy" })

    // Fire system prompt transform hook
    await Plugin.trigger(
      "experimental.chat.system.transform",
      { sessionID: input.sessionID, model: input.model },
      { system: streamInput.system },
    )

    // Fire message transform hook
    await Plugin.trigger(
      "experimental.chat.messages.transform",
      { sessionID: input.sessionID, model: input.model },
      { messages: streamInput.messages },
    )

    // Track snapshot before execution
    const snapshot = await Snapshot.track()
    await Session.updatePart({
      id: PartID.ascending(),
      messageID: input.assistantMessage.id,
      sessionID: input.sessionID,
      snapshot,
      type: "step-start",
    })

    // Set up incremental streaming via bus event subscriptions
    let currentTextPart: MessageV2.TextPart | undefined
    let reasoningParts: Record<string, MessageV2.ReasoningPart> = {}
    const toolcalls: Record<string, MessageV2.ToolPart> = {}

    // Subscribe to text deltas for incremental TUI updates
    const textUnsub = Bus.subscribe(Harness.Event.TextDelta, async (evt) => {
      const props = evt.properties
      if (props.sessionID !== input.sessionID) return

      if (!currentTextPart) {
        currentTextPart = {
          id: PartID.ascending(),
          messageID: input.assistantMessage.id,
          sessionID: input.sessionID,
          type: "text",
          text: "",
          time: { start: Date.now() },
        }
        await Session.updatePart(currentTextPart)
      }

      currentTextPart.text += props.text
      await Session.updatePartDelta({
        sessionID: input.sessionID,
        messageID: input.assistantMessage.id,
        partID: currentTextPart.id,
        field: "text",
        delta: props.text,
      })
    })

    // Subscribe to reasoning deltas
    const reasoningUnsub = Bus.subscribe(Harness.Event.ReasoningDelta, async (evt) => {
      const props = evt.properties
      if (props.sessionID !== input.sessionID) return

      if (!(props.id in reasoningParts)) {
        const part: MessageV2.ReasoningPart = {
          id: PartID.ascending(),
          messageID: input.assistantMessage.id,
          sessionID: input.sessionID,
          type: "reasoning",
          text: "",
          time: { start: Date.now() },
        }
        reasoningParts[props.id] = part
        await Session.updatePart(part)
      }

      const rPart = reasoningParts[props.id]
      rPart.text += props.text
      await Session.updatePartDelta({
        sessionID: input.sessionID,
        messageID: input.assistantMessage.id,
        partID: rPart.id,
        field: "text",
        delta: props.text,
      })
    })

    // Subscribe to tool starts for incremental tool part creation
    const toolStartUnsub = Bus.subscribe(Harness.Event.ToolStart, async (evt) => {
      const props = evt.properties
      if (props.sessionID !== input.sessionID) return

      // Finalize current text part before tool execution
      if (currentTextPart) {
        currentTextPart.text = currentTextPart.text.trimEnd()
        const textOutput = await Plugin.trigger(
          "experimental.text.complete",
          {
            sessionID: input.sessionID,
            messageID: input.assistantMessage.id,
            partID: currentTextPart.id,
          },
          { text: currentTextPart.text },
        )
        currentTextPart.text = textOutput.text
        currentTextPart.time = { start: currentTextPart.time?.start ?? Date.now(), end: Date.now() }
        await Session.updatePart(currentTextPart)
        currentTextPart = undefined
      }

      const existing = toolcalls[props.toolCallId]
      if (existing) {
        const state = existing.state as any
        const part = await Session.updatePart({
          ...existing,
          tool: props.tool,
          callID: props.toolCallId,
          state: {
            ...state,
            status: "running",
            input: props.args ?? state?.input ?? {},
            time: {
              start: state?.time?.start ?? Date.now(),
            },
          },
        })
        toolcalls[props.toolCallId] = part as MessageV2.ToolPart
        log.warn("toolStart:duplicate", {
          callId: props.toolCallId,
          tool: props.tool,
        })
        return
      }

      const part = await Session.updatePart({
        id: PartID.ascending(),
        messageID: input.assistantMessage.id,
        sessionID: input.sessionID,
        type: "tool",
        tool: props.tool,
        callID: props.toolCallId,
        state: {
          status: "running",
          input: props.args ?? {},
          time: { start: Date.now() },
        },
      })
      toolcalls[props.toolCallId] = part as MessageV2.ToolPart
      log.info("toolStart:tracked", {
        callId: props.toolCallId,
        tool: props.tool,
        trackedCount: Object.keys(toolcalls).length,
      })
    })

    // Subscribe to tool completions
    async function finishTool(p: {
      sessionID: SessionID
      callId: string
      tool: string
      output: string
      args?: any
      status?: "completed" | "error"
    }) {
      let id = p.callId
      let match = toolcalls[id]
      if (!match) {
        const items = Object.entries(toolcalls).filter(([, item]) => sameTool(item.tool, p.tool))
        if (items.length === 1) {
          id = items[0][0]
          match = items[0][1]
          log.warn("tool end resolved by canonical name", {
            expected: id,
            received: p.callId,
            tool: p.tool,
          })
        }
      }
      if (!match) {
        log.warn("tool ended with no tracked part", {
          callId: p.callId,
          tool: p.tool,
          trackedKeys: Object.keys(toolcalls),
          output: p.output,
        })
        return
      }

      const meta = toolMetadataStore.get(metadataKey(p.sessionID, id))
      const state = match.state as any
      const args = (() => {
        const current = state?.input ?? {}
        if (Object.keys(current).length > 0) return current
        return p.args ?? {}
      })()
      const status = p.status ?? "completed"

      await Session.updatePart({
        ...match,
        state: status === "completed"
          ? {
              status,
              input: args,
              output: p.output,
              title: meta?.title ?? DEEPAGENT_TOOL_TITLES[match.tool] ?? DEEPAGENT_TOOL_TITLES[p.tool] ?? match.tool,
              metadata: meta?.metadata ?? {},
              time: {
                start: state?.time?.start ?? Date.now(),
                end: Date.now(),
              },
              attachments: meta?.attachments,
            }
          : {
              status,
              input: args,
              error: p.output,
              title: meta?.title ?? DEEPAGENT_TOOL_TITLES[match.tool] ?? DEEPAGENT_TOOL_TITLES[p.tool] ?? match.tool,
              metadata: meta?.metadata ?? {},
              time: {
                start: state?.time?.start ?? Date.now(),
                end: Date.now(),
              },
              attachments: meta?.attachments,
          },
      })

      delete toolcalls[id]
      toolMetadataStore.delete(metadataKey(p.sessionID, id))
      if (id !== p.callId) {
        toolMetadataStore.delete(metadataKey(p.sessionID, p.callId))
      }
    }

    const toolEndUnsub = Bus.subscribe(Harness.Event.ToolEnd, async (evt) => {
      const props = evt.properties
      if (props.sessionID !== input.sessionID) return

      log.info("toolEnd:resolved", {
        callId: props.toolCallId,
        tool: props.tool,
        remainingCount: Object.keys(toolcalls).length - 1,
      })
      await finishTool({
        sessionID: input.sessionID,
        callId: props.toolCallId,
        tool: props.tool,
        output: props.output,
      })
    })

    try {
      // Run the harness
      const harnessResult = await Harness.run({
        sessionID: input.sessionID,
        messageID: input.assistantMessage.id,
        model: input.model,
        agent: streamInput.agent,
        tools: streamInput.tools,
        messages: streamInput.messages,
        system: streamInput.system,
        abort: streamInput.abort,
        permission: streamInput.permission,
        onPermission: streamInput.onPermission,
      })

      // Finalize any remaining text part
      if (currentTextPart) {
        currentTextPart.text = currentTextPart.text.trimEnd()
        const textOutput = await Plugin.trigger(
          "experimental.text.complete",
          {
            sessionID: input.sessionID,
            messageID: input.assistantMessage.id,
            partID: currentTextPart.id,
          },
          { text: currentTextPart.text },
        )
        currentTextPart.text = textOutput.text
        currentTextPart.time = { start: currentTextPart.time?.start ?? Date.now(), end: Date.now() }
        await Session.updatePart(currentTextPart)
        currentTextPart = undefined
      }

      // Finalize any remaining reasoning parts
      for (const [id, rp] of Object.entries(reasoningParts)) {
        rp.text = rp.text.trimEnd()
        rp.time = { start: rp.time?.start ?? Date.now(), end: Date.now() }
        await Session.updatePart(rp)
      }
      reasoningParts = {}

      const calls = harnessResult.toolCalls ?? []
      const used = new Set<number>()
      const pick = (callId: string, tool: string) => {
        const exact = calls.findIndex((item, idx) => !used.has(idx) && item.callId === callId)
        if (exact >= 0) {
          used.add(exact)
          return calls[exact]
        }
        const byName = calls.findIndex((item, idx) => !used.has(idx) && sameTool(item.name, tool))
        if (byName >= 0) {
          used.add(byName)
          return calls[byName]
        }
      }

      for (const [callId, tp] of Object.entries(toolcalls)) {
        const item = pick(callId, tp.tool)
        if (!item) continue
        const status = item.output.startsWith("Tool execution aborted") ? "error" : "completed"
        log.warn("tool resolved from harness result fallback", {
          callId,
          tool: item.name,
          status,
        })
        await finishTool({
          sessionID: input.sessionID,
          callId,
          tool: item.name,
          output: item.output,
          args: item.args,
          status,
        })
      }

      // Safety net: mark any truly orphaned tool parts (should rarely happen
      // now that harness.ts emits synthetic ToolEnd for pending tools AND
      // the catch block also resolves pending tools on error paths)
      const orphanEntries = Object.entries(toolcalls)
      if (orphanEntries.length > 0) {
        log.warn("orphaned tools detected", {
          count: orphanEntries.length,
          tools: orphanEntries.map(([id, tp]) => ({
            id,
            tool: tp.tool,
            args: (tp.state as any)?.input ?? {},
          })),
        })
      }
      for (const [callId, tp] of orphanEntries) {
        const tpState = tp.state as any
        const error = [
          "Tool execution aborted (orphaned)",
          `tool: ${tp.tool}`,
          `call_id: ${callId}`,
          `args: ${JSON.stringify(tpState?.input ?? {})}`,
          "reason: tool started but no matching ToolEnd was tracked before the harness finished",
        ].join("\n")
        log.warn("orphaned tool part", {
          callId,
          tool: tp.tool,
          args: tpState?.input ?? {},
        })
        await Session.updatePart({
          ...tp,
          state: {
            status: "error",
            input: tpState?.input ?? {},
            error,
            time: {
              start: tpState?.time?.start ?? Date.now(),
              end: Date.now(),
            },
          },
        })
      }

      // Compute cost using Session.getUsage() for accurate pricing
      const tu = harnessResult.tokenUsage ?? { prompt: 0, completion: 0, reasoning: 0, cacheRead: 0, cacheWrite: 0 }
      const usage = Session.getUsage({
        model: input.model,
        usage: {
          inputTokens: tu.prompt,
          outputTokens: tu.completion,
          totalTokens: tu.prompt + tu.completion,
          reasoningTokens: tu.reasoning,
          cachedInputTokens: tu.cacheRead,
        },
        metadata: tu.cacheWrite > 0
          ? { anthropic: { cacheCreationInputTokens: tu.cacheWrite } }
          : undefined,
      })

      input.assistantMessage.tokens = usage.tokens
      input.assistantMessage.cost += usage.cost

      // Record step finish
      const finishSnapshot = await Snapshot.track()
      await Session.updatePart({
        id: PartID.ascending(),
        reason: harnessResult.status === "stop" ? "stop" : "tool-calls",
        snapshot: finishSnapshot,
        messageID: input.assistantMessage.id,
        sessionID: input.sessionID,
        type: "step-finish",
        tokens: usage.tokens,
        cost: usage.cost,
      })

      // Track patches
      if (snapshot) {
        const patch = await Snapshot.patch(snapshot)
        if (patch.files.length) {
          await Session.updatePart({
            id: PartID.ascending(),
            messageID: input.assistantMessage.id,
            sessionID: input.sessionID,
            type: "patch",
            hash: patch.hash,
            files: patch.files,
          })
        }
      }

      input.assistantMessage.finish = harnessResult.status === "stop" ? "stop" : "tool-calls"
      input.assistantMessage.time.completed = Date.now()
      await Session.updateMessage(input.assistantMessage)

      SessionSummary.summarize({
        sessionID: input.sessionID,
        messageID: input.assistantMessage.parentID,
      })

      // Check for compaction need
      if (
        !input.assistantMessage.summary &&
        (await SessionCompaction.isOverflow({
          tokens: usage.tokens,
          model: input.model,
        }))
      ) {
        return "compact"
      }

      if (harnessResult.status === "stop" || harnessResult.status === "interrupted") return "stop"
      if (input.assistantMessage.error) return "stop"
      return "continue"
    } finally {
      // Always clean up subscriptions and session metadata
      textUnsub()
      reasoningUnsub()
      toolStartUnsub()
      toolEndUnsub()
      clearSessionMetadata(input.sessionID)
    }
  }
}
