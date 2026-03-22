/**
 * Permission Middleware — HITL (Human-in-the-Loop) permission handling
 * for the LangGraph agent path.
 *
 * Uses the existing Permission.ask() async function which:
 * 1. Evaluates rules against the merged ruleset
 * 2. If "ask" → publishes Permission.Event.Asked via Bus
 * 3. Waits on an Effect Deferred until user responds via TUI
 * 4. Throws RejectedError/DeniedError/CorrectedError on denial
 *
 * This replaces the LangGraph interrupt() approach which is structurally
 * incompatible with the Effect-based TUI permission dialog.
 */
import { Permission } from "../permission"
import { Log } from "../util/log"
import type { SessionID, MessageID } from "../session/schema"
import type { Agent } from "./agent"

const log = Log.create({ service: "permission-middleware" })

export namespace PermissionMiddleware {
  export interface PermissionRequest {
    permission: string
    patterns: string[]
    tool?: string
    metadata?: Record<string, any>
    always?: string[]
  }

  /**
   * Create an onPermission callback that bridges to the existing
   * Permission.ask() system. Passed to Harness.run() config and
   * forwarded to tools via ToolBridgeContext.onPermission.
   *
   * When a tool calls ctx.ask(), this callback delegates to
   * Permission.ask() which handles the full flow:
   * evaluate → Bus event → Deferred wait → TUI response
   */
  export function createPermissionCallback(input: {
    sessionID: SessionID
    messageID: MessageID
    agent: Agent.Info
    sessionPermission?: Permission.Ruleset
  }): (request: PermissionRequest) => Promise<void> {
    return async (request: PermissionRequest) => {
      log.info("permission check", {
        permission: request.permission,
        patterns: request.patterns,
        tool: request.tool,
      })

      const ruleset = Permission.merge(
        input.agent.permission ?? [],
        input.sessionPermission ?? [],
      )

      // Permission.ask() is an async function that:
      // - Evaluates rules (allow/deny/ask)
      // - For "ask": publishes Bus event, waits on Deferred
      // - Throws Permission.RejectedError/DeniedError on denial
      await Permission.ask({
        permission: request.permission,
        patterns: request.patterns,
        sessionID: input.sessionID,
        metadata: request.metadata ?? {},
        always: request.always ?? request.patterns,
        tool: {
          messageID: input.messageID,
          callID: request.tool ?? "",
        },
        ruleset,
      })
    }
  }

  /**
   * Check for doom loop: same tool called with same input N times.
   * Returns true if execution should proceed, false if blocked.
   *
   * @param threshold - Number of consecutive identical calls before blocking (default: 3).
   *   Can be overridden via config `agentSettings.doomLoopThreshold`.
   */
  export function checkDoomLoop(
    toolName: string,
    toolInput: string,
    history: Array<{ tool: string; input: string }>,
    threshold = 3,
  ): boolean {
    const lastN = history.slice(-threshold)

    if (lastN.length < threshold) return true

    return !lastN.every(
      (h) => h.tool === toolName && h.input === toolInput,
    )
  }
}
