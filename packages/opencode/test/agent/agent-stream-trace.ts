#!/usr/bin/env bun
/**
 * Agent Stream Trace — Full Diagnostic of Agent Internals
 *
 * This script runs a REAL agent against the REAL codebase and captures
 * EVERYTHING the agent does into a readable markdown file:
 *
 *   1. Agent reasoning / thinking
 *   2. Agent text messages
 *   3. Tool calls — name, ID, input parameters (flags empty/missing args)
 *   4. Tool messages — results, errors, duration
 *   5. Parallel tool call behavior — what happens when multiple calls fire
 *   6. Empty-input tool calls — why they happen, what breaks
 *   7. Error handling — does the system recover or shut down?
 *
 * Run:
 *   cd packages/opencode && bun run test/agent/agent-stream-trace.ts
 *
 * Output:
 *   test/agent/agent-stream-trace-output.md
 */

// ─── Load .env ──────────────────────────────────────────────────────────────
import os from "os"
import path from "path"
import fs from "fs/promises"

const envPath = path.resolve(import.meta.dir, "../../../../.env")
try {
  const envContent = await fs.readFile(envPath, "utf-8")
  for (const line of envContent.split("\n")) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith("#")) continue
    const eqIdx = trimmed.indexOf("=")
    if (eqIdx === -1) continue
    const key = trimmed.slice(0, eqIdx).trim()
    let value = trimmed.slice(eqIdx + 1).trim()
    if (value.startsWith("'")) {
      const end = value.indexOf("'", 1)
      if (end !== -1) value = value.slice(1, end)
    } else if (value.startsWith('"')) {
      const end = value.indexOf('"', 1)
      if (end !== -1) value = value.slice(1, end)
    } else {
      const c = value.indexOf("#")
      if (c !== -1) value = value.slice(0, c).trim()
    }
    if (value) process.env[key] = value
  }
  delete process.env.OPENAI_BASE_URL
  delete process.env.OPENAI_API_BASE
  console.log("✓ .env loaded")
  console.log("  OPENAI_API_KEY:", process.env.OPENAI_API_KEY ? `${process.env.OPENAI_API_KEY.slice(0, 12)}...` : "NOT SET")
} catch (e: any) {
  console.error("Failed to load .env:", e.message)
  process.exit(1)
}

// ─── Environment isolation ──────────────────────────────────────────────────
const tmpBase = path.join(os.tmpdir(), "malibu-trace-" + Date.now())
await fs.mkdir(tmpBase, { recursive: true })
process.env["XDG_DATA_HOME"] = path.join(tmpBase, "share")
process.env["XDG_CACHE_HOME"] = path.join(tmpBase, "cache")
process.env["XDG_CONFIG_HOME"] = path.join(tmpBase, "config")
process.env["XDG_STATE_HOME"] = path.join(tmpBase, "state")
process.env["MALIBU_DISABLE_DEFAULT_PLUGINS"] = "true"
const testHome = path.join(tmpBase, "home")
await fs.mkdir(testHome, { recursive: true })
process.env["MALIBU_TEST_HOME"] = testHome
process.env["MALIBU_TEST_MANAGED_CONFIG_DIR"] = path.join(tmpBase, "managed")
const cacheDir = path.join(tmpBase, "cache", "malibu")
await fs.mkdir(cacheDir, { recursive: true })
await fs.writeFile(path.join(cacheDir, "version"), "14")

// ─── Preload ────────────────────────────────────────────────────────────────
await import("../../script/preload-langchain")
const { Log } = await import("../../src/util/log")
Log.init({ print: true, dev: true, level: "INFO" })

// ─── Imports ────────────────────────────────────────────────────────────────
import { AIMessage, AIMessageChunk, HumanMessage, ToolMessage } from "@langchain/core/messages"
import { DynamicStructuredTool } from "@langchain/core/tools"
import { z } from "zod"
import { ChatOpenAI } from "@langchain/openai"
import { LocalShellBackend } from "deepagents"
import type { SubAgent } from "deepagents"
import { createMalibuAgent } from "../../src/agent/create-agent"

// ─── Trace types ────────────────────────────────────────────────────────────

interface TraceEntry {
  seq: number
  timeMs: number
  category: "REASONING" | "TEXT" | "TOOL_CALL_CHUNK" | "TOOL_CALL" | "TOOL_MESSAGE" | "USAGE" | "ERROR" | "SYSTEM"
  data: Record<string, any>
}

// ─── Report writer (streams to file as events arrive) ───────────────────────

class TraceWriter {
  private entries: TraceEntry[] = []
  private seq = 0
  private startTime = performance.now()
  private outputPath: string
  private toolCallInputs = new Map<string, { name: string; args: any; timeMs: number }>()
  private emptyArgsCalls: Array<{ id: string; name: string; timeMs: number }> = []
  private parallelGroups: Array<{ ids: string[]; names: string[]; timeMs: number }> = []
  private errors: Array<{ timeMs: number; message: string; context: string }> = []
  private activeToolCalls = new Map<string, number>() // id → startTimeMs

  constructor(outputPath: string) {
    this.outputPath = outputPath
  }

  elapsed(): number {
    return Math.round(performance.now() - this.startTime)
  }

  add(category: TraceEntry["category"], data: Record<string, any>): TraceEntry {
    const entry: TraceEntry = {
      seq: ++this.seq,
      timeMs: this.elapsed(),
      category,
      data,
    }
    this.entries.push(entry)
    return entry
  }

  // Accumulate streamed arg fragments per tool call ID
  private chunkArgs = new Map<string, string>()

  accumulateChunkArgs(id: string, argsFragment: string) {
    const existing = this.chunkArgs.get(id) || ""
    this.chunkArgs.set(id, existing + argsFragment)
  }

  trackToolCall(id: string, name: string, args: any) {
    const timeMs = this.elapsed()

    // Check: did we accumulate chunk args that differ from the tool_calls args?
    const chunkAccumulated = this.chunkArgs.get(id)
    let resolvedArgs = args
    let argsSource = "tool_calls"
    if (chunkAccumulated) {
      try {
        const parsed = JSON.parse(chunkAccumulated)
        // If tool_calls args are empty but chunks have real args, use chunks
        const tcArgsStr = JSON.stringify(args)
        if ((!args || tcArgsStr === "{}" || tcArgsStr === "null") && Object.keys(parsed).length > 0) {
          resolvedArgs = parsed
          argsSource = "accumulated_chunks"
        }
      } catch { /* partial JSON, not parseable yet */ }
    }

    this.toolCallInputs.set(id, { name, args: resolvedArgs, timeMs })
    this.activeToolCalls.set(id, timeMs)

    // Check for empty/missing args using RESOLVED args
    const argsStr = typeof resolvedArgs === "string" ? resolvedArgs : JSON.stringify(resolvedArgs)
    const isEmpty = !resolvedArgs
      || argsStr === "{}"
      || argsStr === ""
      || argsStr === "null"
      || argsStr === "undefined"
    if (isEmpty) {
      this.emptyArgsCalls.push({ id, name, timeMs })
    }

    return { resolvedArgs, argsSource, chunkAccumulated, isEmpty }
  }

  trackToolResult(toolCallId: string) {
    this.activeToolCalls.delete(toolCallId)
  }

  /**
   * Detect parallel tool calls: multiple tool_calls in the same AIMessageChunk
   * or tool_call_chunks arriving within a tight window.
   */
  trackParallelGroup(calls: Array<{ id: string; name: string }>) {
    if (calls.length >= 2) {
      this.parallelGroups.push({
        ids: calls.map(c => c.id),
        names: calls.map(c => c.name),
        timeMs: this.elapsed(),
      })
    }
  }

  trackError(message: string, context: string) {
    this.errors.push({ timeMs: this.elapsed(), message, context })
  }

  async write(crashed: boolean, crashError?: Error) {
    const lines: string[] = []

    // ─── Header ───
    lines.push("# Agent Stream Trace — Full Diagnostic Report")
    lines.push(`Generated: ${new Date().toISOString()}`)
    lines.push(`Status: ${crashed ? "**CRASHED**" : "**COMPLETED**"}`)
    lines.push(`Total events: ${this.entries.length}`)
    lines.push(`Duration: ${this.elapsed()}ms`)
    lines.push("")

    // ─── Table of Contents ───
    lines.push("## Table of Contents")
    lines.push("1. [Event-by-Event Trace](#event-by-event-trace)")
    lines.push("2. [Tool Call Analysis](#tool-call-analysis)")
    lines.push("3. [Empty/Missing Input Analysis](#emptymissing-input-analysis)")
    lines.push("4. [Parallel Execution Analysis](#parallel-execution-analysis)")
    lines.push("5. [Error Analysis](#error-analysis)")
    if (crashed) lines.push("6. [Crash Details](#crash-details)")
    lines.push("")

    // ─── Section 1: Full Event Trace ───
    lines.push("---")
    lines.push("## Event-by-Event Trace")
    lines.push("")
    lines.push("Every event the agent produced, in order. This is the raw stream of consciousness.")
    lines.push("")

    for (const entry of this.entries) {
      const time = `[${String(entry.timeMs).padStart(6)}ms] #${String(entry.seq).padStart(4)}`

      switch (entry.category) {
        case "REASONING": {
          lines.push(`${time} **REASONING**`)
          lines.push("```")
          lines.push(entry.data.text || "(empty)")
          lines.push("```")
          lines.push("")
          break
        }
        case "TEXT": {
          lines.push(`${time} **TEXT**`)
          lines.push("```")
          lines.push(entry.data.text || "(empty)")
          lines.push("```")
          lines.push("")
          break
        }
        case "TOOL_CALL_CHUNK": {
          const d = entry.data
          const argsDisplay = d.args || "(no args in this chunk)"
          lines.push(`${time} **TOOL_CALL_CHUNK** name=\`${d.name || "(none)"}\` id=\`${d.id}\` index=${d.index ?? "?"}`)
          if (d.args) {
            lines.push(`  args fragment: \`${argsDisplay}\``)
          }
          lines.push("")
          break
        }
        case "TOOL_CALL": {
          const d = entry.data
          const rawArgs = d.args_from_tool_calls ?? d.args
          const resolvedArgs = d.args_resolved ?? d.args
          const rawStr = typeof rawArgs === "string" ? rawArgs : JSON.stringify(rawArgs, null, 2)
          const resolvedStr = typeof resolvedArgs === "string" ? resolvedArgs : JSON.stringify(resolvedArgs, null, 2)
          const isEmpty = d.is_empty ?? (!resolvedArgs || resolvedStr === "{}")
          const flag = isEmpty ? " ⚠️ EMPTY ARGS" : ""
          const sourceNote = d.args_source === "accumulated_chunks" ? " (resolved from streamed chunks)" : ""
          lines.push(`${time} **TOOL_CALL**${flag}${sourceNote}`)
          lines.push(`  tool: \`${d.name}\``)
          lines.push(`  id:   \`${d.id}\``)
          lines.push(`  args (from tool_calls):`)
          lines.push("  ```json")
          lines.push(`  ${rawStr}`)
          lines.push("  ```")
          if (d.args_source === "accumulated_chunks") {
            lines.push(`  args (resolved from accumulated chunks):`)
            lines.push("  ```json")
            lines.push(`  ${resolvedStr}`)
            lines.push("  ```")
          }
          if (d.chunk_accumulated_raw) {
            lines.push(`  raw chunk accumulation: \`${d.chunk_accumulated_raw}\``)
          }
          if (isEmpty) {
            lines.push("  **>>> WARNING: This tool call has NO input parameters even after chunk accumulation! <<<**")
            lines.push("  The LLM genuinely sent empty args, OR args arrive in later chunks not yet accumulated.")
          }
          lines.push("")
          break
        }
        case "TOOL_MESSAGE": {
          const d = entry.data
          const isError = d.content?.startsWith("Error:") || d.content?.includes("invalid") || d.content?.includes("failed")
          const flag = isError ? " ❌ ERROR RESPONSE" : ""
          lines.push(`${time} **TOOL_MESSAGE**${flag}`)
          lines.push(`  tool_call_id: \`${d.tool_call_id}\``)
          lines.push(`  name: \`${d.name || "(unknown)"}\``)
          lines.push(`  duration: ${d.durationMs != null ? d.durationMs + "ms" : "unknown"}`)
          lines.push("  content:")
          lines.push("  ```")
          // Limit content to 2000 chars for readability
          const content = d.content || "(empty)"
          lines.push(`  ${content.length > 2000 ? content.slice(0, 2000) + "\n  ... (truncated)" : content}`)
          lines.push("  ```")
          if (isError) {
            lines.push("  **>>> This tool returned an error. See Error Analysis section. <<<**")
          }
          lines.push("")
          break
        }
        case "USAGE": {
          const d = entry.data
          lines.push(`${time} **USAGE** input=${d.input_tokens} output=${d.output_tokens}`)
          lines.push("")
          break
        }
        case "ERROR": {
          lines.push(`${time} **ERROR**`)
          lines.push("  ```")
          lines.push(`  ${entry.data.message}`)
          if (entry.data.stack) {
            lines.push(`  ${entry.data.stack}`)
          }
          lines.push("  ```")
          lines.push("")
          break
        }
        case "SYSTEM": {
          lines.push(`${time} **SYSTEM** ${entry.data.message}`)
          lines.push("")
          break
        }
      }
    }

    // ─── Section 2: Tool Call Analysis ───
    lines.push("---")
    lines.push("## Tool Call Analysis")
    lines.push("")
    lines.push("Every tool call the agent made, with full input/output pairing.")
    lines.push("")

    const toolResults = new Map<string, TraceEntry>()
    for (const e of this.entries) {
      if (e.category === "TOOL_MESSAGE") toolResults.set(e.data.tool_call_id, e)
    }

    let callNum = 0
    for (const [id, info] of this.toolCallInputs) {
      callNum++
      const result = toolResults.get(id)
      const argsStr = typeof info.args === "string" ? info.args : JSON.stringify(info.args, null, 2)
      const isEmpty = !info.args || argsStr === "{}" || argsStr === "" || argsStr === "null"
      const chunkRaw = this.chunkArgs.get(id)

      lines.push(`### Call #${callNum}: \`${info.name}\``)
      lines.push(`- ID: \`${id}\``)
      lines.push(`- Time: ${info.timeMs}ms`)
      lines.push(`- Input args empty: **${isEmpty ? "YES ⚠️" : "no"}**`)
      lines.push("- Resolved input:")
      lines.push("  ```json")
      lines.push(`  ${argsStr}`)
      lines.push("  ```")
      if (chunkRaw) {
        lines.push(`- Raw streamed chunks: \`${chunkRaw}\``)
      }

      if (result) {
        const content = result.data.content || "(empty)"
        const isError = content.startsWith("Error:") || content.includes("invalid")
        lines.push(`- Output received: ${result.data.timeMs}ms (duration: ${result.data.durationMs ?? "?"}ms)`)
        lines.push(`- Output is error: **${isError ? "YES ❌" : "no"}**`)
        lines.push("- Output:")
        lines.push("  ```")
        lines.push(`  ${content.length > 1000 ? content.slice(0, 1000) + "\n  ... (truncated)" : content}`)
        lines.push("  ```")
      } else {
        lines.push("- Output: **NEVER RECEIVED** (orphaned — likely a middleware tool like `task`)")
      }
      lines.push("")
    }

    // ─── Section 3: Empty/Missing Input Analysis ───
    lines.push("---")
    lines.push("## Empty/Missing Input Analysis")
    lines.push("")
    if (this.emptyArgsCalls.length === 0) {
      lines.push("**No tool calls with empty/missing inputs were detected.**")
    } else {
      lines.push(`**${this.emptyArgsCalls.length} tool call(s) had empty or missing input parameters:**`)
      lines.push("")
      for (const call of this.emptyArgsCalls) {
        lines.push(`### Empty-args call: \`${call.name}\` at ${call.timeMs}ms`)
        lines.push(`- Tool call ID: \`${call.id}\``)
        const result = toolResults.get(call.id)
        if (result) {
          lines.push(`- Tool response: \`${result.data.content?.slice(0, 500)}\``)
          const isError = result.data.content?.startsWith("Error:")
          lines.push(`- Was this an error? **${isError ? "YES" : "no"}**`)
          lines.push(`- Did the system recover? **${isError ? "Check if agent continued after this" : "N/A — tool succeeded despite empty args"}**`)
        } else {
          lines.push("- Tool response: **NEVER RECEIVED**")
          lines.push("- This could mean the system STOPPED after this call")
        }
        lines.push("")
      }

      lines.push("### Why do empty-args calls happen?")
      lines.push("")
      lines.push("Possible causes:")
      lines.push("1. **Streaming accumulation**: `tool_call_chunks` arrive with args spread across multiple chunks.")
      lines.push("   The TOOL_CALL entry in the trace may show empty args if it was logged from the first chunk")
      lines.push("   before subsequent chunks filled in the arguments.")
      lines.push("2. **LLM hallucination**: The model genuinely sent empty args for a tool that requires them.")
      lines.push("3. **Provider format mismatch**: Some providers (GPT-5.4) send `tool_calls` with partially")
      lines.push("   populated args alongside `tool_call_chunks` with the full streamed args.")
      lines.push("4. **Middleware injection**: Middleware tools like `task` may have their args handled internally.")
      lines.push("")
    }

    // ─── Section 4: Parallel Execution Analysis ───
    lines.push("---")
    lines.push("## Parallel Execution Analysis")
    lines.push("")
    if (this.parallelGroups.length === 0) {
      lines.push("**No parallel tool call groups were detected.**")
    } else {
      lines.push(`**${this.parallelGroups.length} parallel tool call group(s) detected:**`)
      lines.push("")
      for (let i = 0; i < this.parallelGroups.length; i++) {
        const group = this.parallelGroups[i]
        lines.push(`### Parallel Group #${i + 1} at ${group.timeMs}ms`)
        lines.push(`- Calls: ${group.names.map((n, j) => `\`${n}\` (${group.ids[j]})`).join(", ")}`)
        lines.push(`- Count: ${group.ids.length} parallel calls`)
        lines.push("")

        // Check if all got results
        const results = group.ids.map(id => toolResults.get(id))
        const gotResults = results.filter(Boolean).length
        const missing = results.filter(r => !r).length
        lines.push(`- Results received: ${gotResults}/${group.ids.length}`)
        if (missing > 0) {
          lines.push(`- **${missing} call(s) did NOT get a ToolMessage response**`)
          lines.push("  This is expected for middleware tools (task) but problematic for regular tools.")
        }

        // Check timing of results
        const resultTimes = results.filter(Boolean).map(r => r!.data.timeMs)
        if (resultTimes.length >= 2) {
          const spread = Math.max(...resultTimes) - Math.min(...resultTimes)
          lines.push(`- Result timing spread: ${spread}ms (first result at ${Math.min(...resultTimes)}ms, last at ${Math.max(...resultTimes)}ms)`)
          if (spread > 5000) {
            lines.push("  **>>> Large timing spread — one call may have blocked the other <<<**")
          }
        }
        lines.push("")
      }
    }

    // ─── Section 5: Error Analysis ───
    lines.push("---")
    lines.push("## Error Analysis")
    lines.push("")

    // Collect all errors: explicit errors + tool messages with error content
    const allErrors: Array<{ timeMs: number; source: string; message: string }> = []
    for (const e of this.errors) {
      allErrors.push({ timeMs: e.timeMs, source: e.context, message: e.message })
    }
    for (const e of this.entries) {
      if (e.category === "TOOL_MESSAGE") {
        const content = e.data.content || ""
        if (content.startsWith("Error:") || content.includes("ToolInputParsingException") || content.includes("invalid arguments")) {
          allErrors.push({ timeMs: e.data.timeMs, source: `ToolMessage for ${e.data.name}`, message: content.slice(0, 500) })
        }
      }
    }

    if (allErrors.length === 0) {
      lines.push("**No errors detected during execution.**")
    } else {
      lines.push(`**${allErrors.length} error(s) detected:**`)
      lines.push("")
      for (const err of allErrors) {
        lines.push(`### Error at ${err.timeMs}ms`)
        lines.push(`- Source: ${err.source}`)
        lines.push("- Message:")
        lines.push("  ```")
        lines.push(`  ${err.message}`)
        lines.push("  ```")
        lines.push("")
      }

      lines.push("### Error Recovery Analysis")
      lines.push("")
      // Check if events continued after each error
      for (const err of allErrors) {
        const eventsAfter = this.entries.filter(e => e.timeMs > err.timeMs)
        if (eventsAfter.length > 0) {
          lines.push(`- Error at ${err.timeMs}ms: **${eventsAfter.length} events followed** — system recovered`)
        } else {
          lines.push(`- Error at ${err.timeMs}ms: **NO events followed** — system STOPPED ⚠️`)
        }
      }
      lines.push("")
    }

    // ─── Section 6: Crash Details ───
    if (crashed && crashError) {
      lines.push("---")
      lines.push("## Crash Details")
      lines.push("")
      lines.push("The agent stream terminated with an unhandled exception.")
      lines.push("")
      lines.push("```")
      lines.push(`Error: ${crashError.message}`)
      lines.push(`Name: ${crashError.name}`)
      lines.push("")
      lines.push("Stack trace:")
      lines.push(crashError.stack ?? "No stack trace available")
      lines.push("```")
      lines.push("")

      // Analyze what was happening when it crashed
      const lastEvents = this.entries.slice(-5)
      lines.push("### Last 5 events before crash:")
      lines.push("")
      for (const e of lastEvents) {
        lines.push(`- #${e.seq} [${e.timeMs}ms] ${e.category}: ${JSON.stringify(e.data).slice(0, 200)}`)
      }
      lines.push("")

      // Were there pending tool calls?
      const unresolvedTools = [...this.toolCallInputs.entries()].filter(([id]) => !toolResults.has(id))
      if (unresolvedTools.length > 0) {
        lines.push("### Unresolved tool calls at crash time:")
        lines.push("")
        for (const [id, info] of unresolvedTools) {
          lines.push(`- \`${info.name}\` (${id}) — called at ${info.timeMs}ms, never got result`)
        }
        lines.push("")
      }
    }

    // ─── Final Summary ───
    lines.push("---")
    lines.push("## Summary Statistics")
    lines.push("")
    const textEntries = this.entries.filter(e => e.category === "TEXT")
    const reasoningEntries = this.entries.filter(e => e.category === "REASONING")
    const toolCallEntries = this.entries.filter(e => e.category === "TOOL_CALL")
    const toolMsgEntries = this.entries.filter(e => e.category === "TOOL_MESSAGE")
    const chunkEntries = this.entries.filter(e => e.category === "TOOL_CALL_CHUNK")

    lines.push(`| Metric | Value |`)
    lines.push(`|--------|-------|`)
    lines.push(`| Total events | ${this.entries.length} |`)
    lines.push(`| Text messages | ${textEntries.length} |`)
    lines.push(`| Reasoning chunks | ${reasoningEntries.length} |`)
    lines.push(`| Tool call chunks | ${chunkEntries.length} |`)
    lines.push(`| Complete tool calls | ${toolCallEntries.length} |`)
    lines.push(`| Tool messages (results) | ${toolMsgEntries.length} |`)
    lines.push(`| Empty-args calls | ${this.emptyArgsCalls.length} |`)
    lines.push(`| Parallel groups | ${this.parallelGroups.length} |`)
    lines.push(`| Errors | ${allErrors.length} |`)
    lines.push(`| Crashed | ${crashed ? "YES" : "no"} |`)
    lines.push(`| Duration | ${this.elapsed()}ms |`)
    lines.push("")

    await fs.writeFile(this.outputPath, lines.join("\n"), "utf-8")
    console.log(`\nTrace written to: ${this.outputPath}`)
  }
}

// ─── Build the agent ────────────────────────────────────────────────────────

async function run() {
  const outputPath = path.join(import.meta.dir, "agent-stream-trace-output.md")
  const trace = new TraceWriter(outputPath)

  // Create a test repo with REAL code to explore
  const repoDir = path.join(tmpBase, "repo")
  await fs.mkdir(repoDir, { recursive: true })
  await fs.mkdir(path.join(repoDir, "src", "api"), { recursive: true })
  await fs.mkdir(path.join(repoDir, "src", "utils"), { recursive: true })
  await fs.mkdir(path.join(repoDir, "tests"), { recursive: true })

  // Create realistic files for the agent to explore
  await fs.writeFile(path.join(repoDir, "README.md"), `# TaskFlow API
A REST API for task management built with Express and TypeScript.

## Features
- CRUD operations for tasks
- User authentication with JWT
- Rate limiting and input validation
- PostgreSQL database with Prisma ORM

## Getting Started
\`\`\`bash
npm install
npm run dev
\`\`\`
`)

  await fs.writeFile(path.join(repoDir, "package.json"), JSON.stringify({
    name: "taskflow-api",
    version: "1.0.0",
    scripts: { dev: "tsx watch src/server.ts", build: "tsc", test: "vitest" },
    dependencies: { express: "^4.18", prisma: "^5.0", jsonwebtoken: "^9.0", zod: "^3.22" },
    devDependencies: { typescript: "^5.3", vitest: "^1.0", tsx: "^4.0" },
  }, null, 2))

  await fs.writeFile(path.join(repoDir, "src", "server.ts"), `
import express from 'express'
import { taskRouter } from './api/tasks'
import { authMiddleware } from './utils/auth'
import { rateLimiter } from './utils/rate-limit'

const app = express()
app.use(express.json())
app.use(rateLimiter({ windowMs: 60000, max: 100 }))
app.use('/api/tasks', authMiddleware, taskRouter)

app.listen(3000, () => console.log('Server running on port 3000'))
export default app
`)

  await fs.writeFile(path.join(repoDir, "src", "api", "tasks.ts"), `
import { Router } from 'express'
import { z } from 'zod'
import { prisma } from '../utils/db'

const TaskSchema = z.object({
  title: z.string().min(1).max(200),
  description: z.string().optional(),
  status: z.enum(['pending', 'in_progress', 'done']).default('pending'),
  priority: z.number().int().min(1).max(5).default(3),
})

export const taskRouter = Router()

taskRouter.get('/', async (req, res) => {
  const tasks = await prisma.task.findMany({ where: { userId: req.user.id } })
  res.json(tasks)
})

taskRouter.post('/', async (req, res) => {
  const parsed = TaskSchema.safeParse(req.body)
  if (!parsed.success) return res.status(400).json({ error: parsed.error.flatten() })
  const task = await prisma.task.create({ data: { ...parsed.data, userId: req.user.id } })
  res.status(201).json(task)
})

taskRouter.put('/:id', async (req, res) => {
  const parsed = TaskSchema.partial().safeParse(req.body)
  if (!parsed.success) return res.status(400).json({ error: parsed.error.flatten() })
  const task = await prisma.task.update({
    where: { id: req.params.id, userId: req.user.id },
    data: parsed.data,
  })
  res.json(task)
})

taskRouter.delete('/:id', async (req, res) => {
  await prisma.task.delete({ where: { id: req.params.id, userId: req.user.id } })
  res.status(204).end()
})
`)

  await fs.writeFile(path.join(repoDir, "src", "utils", "auth.ts"), `
import jwt from 'jsonwebtoken'

const JWT_SECRET = process.env.JWT_SECRET || 'dev-secret'

export function authMiddleware(req: any, res: any, next: any) {
  const token = req.headers.authorization?.replace('Bearer ', '')
  if (!token) return res.status(401).json({ error: 'No token provided' })
  try {
    req.user = jwt.verify(token, JWT_SECRET)
    next()
  } catch {
    res.status(401).json({ error: 'Invalid token' })
  }
}

export function generateToken(user: { id: string; email: string }) {
  return jwt.sign(user, JWT_SECRET, { expiresIn: '24h' })
}
`)

  await fs.writeFile(path.join(repoDir, "src", "utils", "rate-limit.ts"), `
const store = new Map<string, { count: number; resetAt: number }>()

export function rateLimiter(opts: { windowMs: number; max: number }) {
  return (req: any, res: any, next: any) => {
    const ip = req.ip || 'unknown'
    const now = Date.now()
    let entry = store.get(ip)
    if (!entry || now > entry.resetAt) {
      entry = { count: 0, resetAt: now + opts.windowMs }
      store.set(ip, entry)
    }
    entry.count++
    if (entry.count > opts.max) {
      return res.status(429).json({ error: 'Too many requests' })
    }
    next()
  }
}
`)

  await fs.writeFile(path.join(repoDir, "src", "utils", "db.ts"), `
// Prisma client singleton
import { PrismaClient } from '@prisma/client'
export const prisma = new PrismaClient()
`)

  await fs.writeFile(path.join(repoDir, "tests", "tasks.test.ts"), `
import { describe, it, expect } from 'vitest'

describe('Task API', () => {
  it('should create a task', async () => {
    // TODO: implement
    expect(true).toBe(true)
  })

  it('should validate task input', async () => {
    // TODO: implement
    expect(true).toBe(true)
  })
})
`)

  const { $ } = await import("bun")
  await $`git init`.cwd(repoDir).quiet()
  await $`git config core.fsmonitor false`.cwd(repoDir).quiet()
  await $`git config user.email "test@test"`.cwd(repoDir).quiet()
  await $`git config user.name "Test"`.cwd(repoDir).quiet()
  await $`git add -A`.cwd(repoDir).quiet()
  await $`git commit -m "init: TaskFlow API project"`.cwd(repoDir).quiet()

  trace.add("SYSTEM", { message: `Test repo created at ${repoDir} with 8 files` })

  // ─── Create tools that simulate real tool behavior ──────────────────────
  // These tools mirror what Malibu's real tools do: read files, search code, etc.

  const searchCodeTool = new DynamicStructuredTool({
    name: "search_code",
    description: "Search for a pattern or keyword across the codebase using regex. Returns matching lines with file paths and line numbers.",
    schema: z.object({
      pattern: z.string().describe("The regex pattern to search for"),
      path: z.string().optional().describe("Directory to search in, relative to repo root. Defaults to '.'"),
      file_type: z.string().optional().describe("File extension filter, e.g. 'ts', 'json'"),
    }),
    func: async ({ pattern, path: searchPath, file_type }) => {
      await new Promise(r => setTimeout(r, 80))
      // Actually search the repo files
      const dir = path.join(repoDir, searchPath || ".")
      const results: string[] = []
      try {
        const files = await walkDir(dir)
        for (const file of files) {
          if (file_type && !file.endsWith(`.${file_type}`)) continue
          const content = await fs.readFile(file, "utf-8")
          const lines = content.split("\n")
          for (let i = 0; i < lines.length; i++) {
            try {
              if (new RegExp(pattern, "i").test(lines[i])) {
                const relPath = path.relative(repoDir, file)
                results.push(`${relPath}:${i + 1}: ${lines[i].trim()}`)
              }
            } catch { /* invalid regex */ }
          }
        }
      } catch (e: any) {
        return `Error searching: ${e.message}`
      }
      if (results.length === 0) return `No matches found for pattern "${pattern}"`
      return `Found ${results.length} match(es):\n${results.slice(0, 20).join("\n")}`
    },
  })

  const readFileTool = new DynamicStructuredTool({
    name: "read_file",
    description: "Read the contents of a file. Returns the full file content with line numbers.",
    schema: z.object({
      file_path: z.string().describe("Path to the file relative to the repo root"),
    }),
    func: async ({ file_path }) => {
      await new Promise(r => setTimeout(r, 50))
      try {
        const content = await fs.readFile(path.join(repoDir, file_path), "utf-8")
        const numbered = content.split("\n").map((line, i) => `${String(i + 1).padStart(4)}| ${line}`).join("\n")
        return numbered
      } catch (e: any) {
        return `Error: Could not read file "${file_path}": ${e.message}`
      }
    },
  })

  const listFilesTool = new DynamicStructuredTool({
    name: "list_files",
    description: "List files and directories in a given path. Returns a tree-like listing.",
    schema: z.object({
      directory: z.string().optional().describe("Directory path relative to repo root. Defaults to '.'"),
    }),
    func: async ({ directory }) => {
      await new Promise(r => setTimeout(r, 30))
      const dir = path.join(repoDir, directory || ".")
      try {
        const entries = await fs.readdir(dir, { withFileTypes: true })
        const lines = entries
          .filter(e => !e.name.startsWith("."))
          .map(e => `${e.isDirectory() ? "📁" : "📄"} ${e.name}`)
        return lines.join("\n") || "(empty directory)"
      } catch (e: any) {
        return `Error: Could not list "${directory}": ${e.message}`
      }
    },
  })

  // ─── Build models ─────────────────────────────────────────────────────
  const model = new ChatOpenAI({
    modelName: "gpt-4o-mini",
    temperature: 0,
    streaming: true,
    apiKey: process.env.OPENAI_API_KEY,
  })

  const subagentModel = new ChatOpenAI({
    modelName: "gpt-4o-mini",
    temperature: 0,
    streaming: true,
    apiKey: process.env.OPENAI_API_KEY,
  })

  const tools = [searchCodeTool, readFileTool, listFilesTool]

  const explore: SubAgent = {
    name: "explore",
    description: "Fast agent for exploring codebases. Use for searching files, reading code, and answering codebase questions.",
    systemPrompt: `You are an explore agent. Use the available tools to explore the codebase and answer the user's question.
Be thorough — use search_code to find patterns, read_file to examine files, and list_files to understand structure.
Keep your final response under 200 words.`,
    model: subagentModel,
    tools,
  }

  const general: SubAgent = {
    name: "general",
    description: "General-purpose agent for complex multi-step tasks. Use for analysis, refactoring plans, etc.",
    systemPrompt: `You are a general-purpose agent. Use the tools to investigate the codebase and provide analysis.
Be thorough with tool usage. Keep your final response under 200 words.`,
    model: subagentModel,
    tools,
  }

  const backend = new LocalShellBackend({ rootDir: repoDir })

  // ─── Build agent ──────────────────────────────────────────────────────
  const { SqliteCheckpointer } = await import("../../src/agent/checkpointer")
  const dbPath = path.join(tmpBase, "checkpoints.db")
  const checkpointer = new SqliteCheckpointer(dbPath)

  let crashed = false
  let crashError: Error | undefined

  let agent: ReturnType<typeof createMalibuAgent>
  try {
    agent = createMalibuAgent({
      model,
      tools,
      systemPrompt: `You are a senior software engineer reviewing a codebase.

You have access to tools: search_code, read_file, list_files, and the task tool for delegating to sub-agents.

When asked to explore a codebase, follow this EXACT plan:
1. First, call list_files to see the project structure
2. Then call the task tool TWICE IN PARALLEL to deploy two explore agents:
   - First agent: "Read and analyze the API routes and authentication"
   - Second agent: "Read and analyze the utility modules and rate limiting"
3. After getting results from both agents, synthesize your findings

IMPORTANT: The two task calls MUST be in the SAME message (parallel tool calls).`,
      checkpointer,
      backend,
      subagents: [explore, general],
      name: "trace-agent",
      isAnthropicModel: false,
    })
    trace.add("SYSTEM", { message: "Agent created with SqliteCheckpointer, 3 tools, 2 sub-agents" })
    console.log("✓ Agent created\n")
  } catch (error: any) {
    trace.add("ERROR", { message: error.message, stack: error.stack })
    trace.trackError(error.message, "agent creation")
    console.error("FATAL:", error.message)
    crashed = true
    crashError = error
    await trace.write(crashed, crashError)
    process.exit(1)
  }

  // ─── Stream the agent ─────────────────────────────────────────────────
  console.log("═══════════════════════════════════════════════════")
  console.log("  STREAMING AGENT — all output captured to trace")
  console.log("═══════════════════════════════════════════════════\n")
  console.log("Prompt: 'Explore this codebase thoroughly. Tell me about the architecture and any issues.'\n")

  const threadId = "trace-" + Date.now()

  try {
    const stream = await agent.stream(
      {
        messages: [new HumanMessage(
          "Explore this TaskFlow API codebase thoroughly. I want to understand the architecture, " +
          "the API routes, authentication, rate limiting, and any code quality issues. " +
          "Deploy sub-agents in parallel to cover different areas."
        )],
      },
      {
        configurable: { thread_id: threadId },
        streamMode: "messages",
      },
    )

    // Accumulate text for buffered text events (avoid per-char noise)
    let textBuffer = ""
    let lastTextTime = 0
    const TEXT_FLUSH_MS = 100

    function flushText() {
      if (textBuffer) {
        trace.add("TEXT", { text: textBuffer })
        textBuffer = ""
      }
    }

    // Track tool_calls arriving in same chunk for parallel detection
    let currentChunkToolCalls: Array<{ id: string; name: string }> = []
    let lastChunkTime = 0
    // Map chunk index → tool call ID (for chunks that only have index, not id)
    const indexToId = new Map<number, string>()

    for await (const event of stream) {
      const [msg] = Array.isArray(event) ? event : [event]
      const now = trace.elapsed()

      if (msg instanceof AIMessageChunk) {
        // --- Text content ---
        if (typeof msg.content === "string" && msg.content) {
          textBuffer += msg.content
          if (now - lastTextTime > TEXT_FLUSH_MS) {
            flushText()
            lastTextTime = now
          }
          process.stdout.write(msg.content)
        } else if (Array.isArray(msg.content)) {
          for (const part of msg.content) {
            const p = part as any
            if (typeof p === "string") {
              textBuffer += p
              process.stdout.write(p)
            } else if (p.type === "text" && p.text) {
              textBuffer += p.text
              process.stdout.write(p.text)
            } else if (p.type === "thinking" && p.thinking) {
              flushText()
              trace.add("REASONING", { text: p.thinking, type: "anthropic-thinking" })
              console.log(`\n  [THINKING] ${p.thinking.slice(0, 100)}...`)
            } else if (p.type === "reasoning" && p.reasoning) {
              flushText()
              trace.add("REASONING", { text: p.reasoning, type: "openai-reasoning" })
              console.log(`\n  [REASONING] ${p.reasoning.slice(0, 100)}...`)
            }
          }
          if (now - lastTextTime > TEXT_FLUSH_MS) {
            flushText()
            lastTextTime = now
          }
        }

        // --- Tool call chunks ---
        // Track index→id mapping for chunks that don't carry an id (only index)
        for (const tc of msg.tool_call_chunks ?? []) {
          const resolvedId = tc.id || indexToId.get(tc.index ?? -1) || null
          if (tc.id && tc.index != null) {
            indexToId.set(tc.index, tc.id)
          }
          if (!resolvedId) continue
          flushText()
          trace.add("TOOL_CALL_CHUNK", {
            id: resolvedId,
            name: tc.name || null,
            args: tc.args || null,
            index: tc.index,
            had_id: !!tc.id,
          })
          // Accumulate args fragments for this tool call
          if (tc.args) {
            trace.accumulateChunkArgs(resolvedId, tc.args)
          }
          if (tc.name) {
            console.log(`\n  [CHUNK] ${tc.name} (${resolvedId})`)
          }
        }

        // --- Complete tool calls ---
        if (msg.tool_calls && msg.tool_calls.length > 0) {
          flushText()

          // Detect parallel: multiple tool_calls in the same message chunk
          const batchCalls: Array<{ id: string; name: string }> = []

          for (const tc of msg.tool_calls) {
            const id = tc.id ?? tc.name
            const tracked = trace.trackToolCall(id, tc.name, tc.args)
            trace.add("TOOL_CALL", {
              id,
              name: tc.name,
              args_from_tool_calls: tc.args,
              args_resolved: tracked.resolvedArgs,
              args_source: tracked.argsSource,
              chunk_accumulated_raw: tracked.chunkAccumulated || null,
              is_empty: tracked.isEmpty,
            })
            batchCalls.push({ id, name: tc.name })

            const resolvedStr = JSON.stringify(tracked.resolvedArgs)
            const preview = resolvedStr.length > 100 ? resolvedStr.slice(0, 100) + "..." : resolvedStr
            console.log(`\n  [TOOL_CALL] ${tc.name} (${id})${tracked.isEmpty ? " ⚠️ EMPTY ARGS" : ""}`)
            console.log(`    tool_calls args: ${JSON.stringify(tc.args)}`)
            if (tracked.argsSource === "accumulated_chunks") {
              console.log(`    resolved args (from chunks): ${preview}`)
            }
          }

          // Track parallel group if multiple calls in same chunk
          if (batchCalls.length >= 2) {
            trace.trackParallelGroup(batchCalls)
            console.log(`\n  >>> PARALLEL GROUP: ${batchCalls.length} calls in same message <<<`)
          }

          // Also detect near-simultaneous calls across chunks
          if (now - lastChunkTime < 50 && currentChunkToolCalls.length > 0) {
            // Merge with previous chunk's calls
            currentChunkToolCalls.push(...batchCalls)
          } else {
            if (currentChunkToolCalls.length >= 2) {
              trace.trackParallelGroup(currentChunkToolCalls)
            }
            currentChunkToolCalls = [...batchCalls]
          }
          lastChunkTime = now
        }

        // --- Usage ---
        const usage = (msg as any).usage_metadata
        if (usage) {
          flushText()
          trace.add("USAGE", {
            input_tokens: usage.input_tokens,
            output_tokens: usage.output_tokens,
          })
        }

      } else if (msg instanceof ToolMessage) {
        flushText()
        const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)
        const toolCallId = (msg as any).tool_call_id ?? ""
        const callInfo = trace.toolCallInputs?.get(toolCallId)

        trace.add("TOOL_MESSAGE", {
          tool_call_id: toolCallId,
          name: msg.name,
          content,
          timeMs: trace.elapsed(),
          durationMs: callInfo ? trace.elapsed() - callInfo.timeMs : undefined,
        })
        trace.trackToolResult(toolCallId)

        const preview = content.length > 150 ? content.slice(0, 150) + "..." : content
        const isError = content.startsWith("Error:") || content.includes("invalid")
        console.log(`\n  [TOOL_RESULT] ${msg.name} (${toolCallId})${isError ? " ❌" : ""}`)
        console.log(`    ${preview}`)

        if (isError) {
          trace.trackError(content.slice(0, 500), `tool result for ${msg.name}`)
        }

      } else if (msg instanceof AIMessage) {
        flushText()
        // Non-chunked AI message (final or tool calls)
        if (msg.tool_calls && msg.tool_calls.length > 0) {
          const batchCalls: Array<{ id: string; name: string }> = []
          for (const tc of msg.tool_calls) {
            const id = tc.id ?? tc.name
            trace.add("TOOL_CALL", { id, name: tc.name, args: tc.args, source: "AIMessage" })
            trace.trackToolCall(id, tc.name, tc.args)
            batchCalls.push({ id, name: tc.name })
          }
          if (batchCalls.length >= 2) {
            trace.trackParallelGroup(batchCalls)
          }
        }
        if (typeof msg.content === "string" && msg.content) {
          trace.add("TEXT", { text: msg.content })
          process.stdout.write(msg.content)
        }
      }
    }

    // Flush any remaining text
    flushText()
    // Check for unresolved parallel group
    if (currentChunkToolCalls.length >= 2) {
      trace.trackParallelGroup(currentChunkToolCalls)
    }

    trace.add("SYSTEM", { message: "Stream completed normally" })
    console.log("\n\n✓ Stream completed")

  } catch (error: any) {
    crashed = true
    crashError = error
    trace.add("ERROR", { message: error.message, name: error.name, stack: error.stack })
    trace.trackError(error.message, "stream iteration")
    console.error("\n\n✗ STREAM CRASHED:", error.message)
    console.error("Stack:", error.stack)
  }

  // ─── Write the trace ──────────────────────────────────────────────────
  await trace.write(crashed, crashError)

  // Cleanup
  try { await fs.rm(tmpBase, { recursive: true, force: true }) } catch {}

  process.exit(crashed ? 1 : 0)
}

// ─── Helpers ────────────────────────────────────────────────────────────────

async function walkDir(dir: string): Promise<string[]> {
  const files: string[] = []
  try {
    const entries = await fs.readdir(dir, { withFileTypes: true })
    for (const entry of entries) {
      if (entry.name.startsWith(".")) continue
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        files.push(...await walkDir(full))
      } else {
        files.push(full)
      }
    }
  } catch { /* skip unreadable dirs */ }
  return files
}

// ─── Run ────────────────────────────────────────────────────────────────────
await run()
