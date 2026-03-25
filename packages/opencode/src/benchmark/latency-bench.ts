/**
 * Malibu Latency Benchmark — Deep Instrumentation v2
 *
 * Instruments EVERY internal function to reveal where time is spent.
 * Monkey-patches key functions globally (before benchmark starts) to
 * capture timing for:
 *
 * MALIBU PRE-AGENT (prompt.ts loop + harness-processor setup):
 *   - createUserMessage: Agent.get, Provider model resolution, DB writes
 *   - loop(): Session.get, MessageV2 fetch, message scanning
 *   - HarnessProcessor: Plugin triggers, Snapshot.track (pre-exec), DB writes
 *   - Harness.run → buildAgentConfig: UnifiedProvider.create, toLangChainTools,
 *     Skill.dirs, buildSubAgents, SystemPrompt, ToolRegistry.all, MCP.tools
 *   - createMalibuAgent: middleware chain assembly
 *
 * AGENT (LangGraph):
 *   - agent.stream() → first AIMessageChunk (LLM TTFT)
 *   - Reasoning/thinking tokens, Text tokens
 *   - Tool calls: ToolStart → ToolEnd
 *   - Second LLM TTFT after tool result
 *
 * MALIBU POST-AGENT (harness-processor finalization + prompt.ts loop exit):
 *   - Text/reasoning part finalization + Plugin triggers
 *   - Cost computation (Session.getUsage)
 *   - Snapshot.track (post-exec) + Snapshot.patch (git diff)
 *   - Session.updateMessage (set finish)
 *   - SessionSummary.summarize (git diffs — fire-and-forget but heavy)
 *   - SessionCompaction.isOverflow check
 *   - Loop re-iteration: re-fetch all messages, check exit condition
 *   - SessionCompaction.prune
 *   - Final MessageV2.stream to find result
 *
 * Usage:
 *   bun run src/benchmark/latency-bench.ts
 *   bun run src/benchmark/latency-bench.ts --prompt "What is 2+2?"
 *   bun run src/benchmark/latency-bench.ts --model openai/gpt-4o
 *   bun run src/benchmark/latency-bench.ts --all
 *   bun run src/benchmark/latency-bench.ts --test simple|bash|read|multi
 */

import { performance } from "perf_hooks"
import { Instance } from "../project/instance"
import { InstanceBootstrap } from "../project/bootstrap"
import { Config } from "../config/config"
import { Session } from "../session"
import { SessionPrompt } from "../session/prompt"
import { Bus } from "../bus"
import { Harness } from "../agent/harness"
import { Log } from "../util/log"
import { ToolRegistry } from "../tool/registry"
import { Snapshot } from "../snapshot"
import { SessionSummary } from "../session/summary"
import { SessionCompaction } from "../session/compaction"
import { Plugin } from "../plugin"
import { UnifiedProvider } from "../provider/unified"
import { Agent } from "../agent/agent"
import { Provider } from "../provider/provider"
import { MessageV2 } from "../session/message-v2"
import { MCP } from "../mcp"
import { SystemPrompt } from "../session/system"
import { InstructionPrompt } from "../session/instruction"
import { Skill } from "../skill"

// ── Types ──────────────────────────────────────────────────────────────

interface TimelineEntry {
  time: number
  label: string
  detail?: string
  category: "malibu-pre" | "agent" | "malibu-post" | "system"
}

interface TextDeltaRecord { time: number; text: string }
interface ToolRecord { tool: string; callId: string; startTime: number; endTime?: number }

interface BenchmarkResult {
  prompt: string
  model: string
  timeline: TimelineEntry[]
  textDeltas: TextDeltaRecord[]
  reasoningDeltas: TextDeltaRecord[]
  tools: ToolRecord[]
  tokenUsage?: { prompt: number; completion: number; reasoning: number; cacheRead: number; cacheWrite: number }
  t0: number
  totalTime: number
}

// ── CLI ────────────────────────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2)
  const result: { prompt?: string; model?: string; all: boolean; test?: string } = { all: false }
  for (let i = 0; i < args.length; i++) {
    const arg = args[i]
    if (arg === "--all") result.all = true
    else if (arg === "--prompt" && args[i + 1]) result.prompt = args[++i]
    else if (arg === "--model" && args[i + 1]) result.model = args[++i]
    else if (arg === "--test" && args[i + 1]) result.test = args[++i]
    else if (arg === "--help" || arg === "-h") {
      console.log(`
Malibu Latency Benchmark — Deep Instrumentation v2

Usage:  bun run src/benchmark/latency-bench.ts [options]

Options:
  --prompt <text>   Custom prompt to benchmark
  --model <id>      Model in "provider/model" format (e.g., openai/gpt-4o)
  --test <name>     Run a named test: simple, bash, read, multi
  --all             Run all default test prompts
  --help            Show this help
`)
      process.exit(0)
    }
  }
  return result
}

// ── Test prompts ───────────────────────────────────────────────────────

const TEST_PROMPTS: Record<string, { name: string; prompt: string; description: string }> = {
  simple: {
    name: "Simple Text",
    prompt: "What is 2+2? Answer in one word only.",
    description: "Pure TTFT + text streaming, no tool calls",
  },
  bash: {
    name: "Bash Tool Call",
    prompt: 'Run this exact bash command and show me the output: echo "hello from benchmark". Do NOT use any other tools. Reply briefly after showing the output.',
    description: "TTFT + Bash tool call + tool execution + second response",
  },
  read: {
    name: "Read Tool Call",
    prompt: "Read the file package.json (in the current directory) and tell me the project name. Use the Read tool. Reply in one sentence.",
    description: "TTFT + Read tool call + second response",
  },
  multi: {
    name: "Multi-Tool",
    prompt: 'First run the bash command: echo "hello benchmark". Then read package.json. Tell me both results briefly.',
    description: "Bash + Read tool calls in sequence",
  },
}

// ── Global instrumentation ─────────────────────────────────────────────

let markFn: (label: string, detail?: string, category?: TimelineEntry["category"]) => void = () => {}

/** Wrap an async function with timing marks */
function wrapAsync<T extends (...args: any[]) => Promise<any>>(
  obj: any,
  key: string,
  label: string,
  category: TimelineEntry["category"],
  detailFn?: (...args: any[]) => string,
): T {
  const original = obj[key]
  obj[key] = async function (this: any, ...args: any[]) {
    const detail = detailFn ? detailFn(...args) : undefined
    markFn(`${label} START`, detail, category)
    try {
      const result = await original.apply(this, args)
      markFn(`${label} END`, detail, category)
      return result
    } catch (err) {
      markFn(`${label} ERROR`, String(err), category)
      throw err
    }
  }
  return original
}

/** Accumulator for high-frequency calls (e.g., Session.updatePart) */
interface CallStats { count: number; totalMs: number; maxMs: number }

function wrapAsyncAccum<T extends (...args: any[]) => Promise<any>>(
  obj: any,
  key: string,
  stats: CallStats,
): T {
  const original = obj[key]
  obj[key] = async function (this: any, ...args: any[]) {
    const start = performance.now()
    const result = await original.apply(this, args)
    const elapsed = performance.now() - start
    stats.count++
    stats.totalMs += elapsed
    if (elapsed > stats.maxMs) stats.maxMs = elapsed
    return result
  }
  return original
}

function installGlobalInstrumentation() {
  const originals: Array<[any, string, any]> = []
  const restore = (obj: any, key: string, orig: any) => { originals.push([obj, key, orig]) }

  // --- MALIBU PRE-AGENT: prompt.ts loop internals ---
  restore(Session, "get", wrapAsync(Session, "get", "Session.get()", "malibu-pre"))
  restore(Session, "create", wrapAsync(Session, "create", "Session.create()", "malibu-pre"))
  restore(Agent, "get", wrapAsync(Agent, "get", "Agent.get()", "malibu-pre", (name) => `agent=${name}`))
  restore(Provider, "getModel", wrapAsync(Provider, "getModel", "Provider.getModel()", "malibu-pre",
    (pid, mid) => `${pid}/${mid}`))
  restore(ToolRegistry, "all", wrapAsync(ToolRegistry, "all", "ToolRegistry.all()", "malibu-pre"))
  restore(MCP, "tools", wrapAsync(MCP, "tools", "MCP.tools()", "malibu-pre"))
  restore(SystemPrompt, "environment", wrapAsync(SystemPrompt, "environment", "SystemPrompt.environment()", "malibu-pre"))
  restore(SystemPrompt, "skills", wrapAsync(SystemPrompt, "skills", "SystemPrompt.skills()", "malibu-pre"))
  restore(InstructionPrompt, "system", wrapAsync(InstructionPrompt, "system", "InstructionPrompt.system()", "malibu-pre"))

  // --- MALIBU PRE-AGENT: Harness.run → buildAgentConfig ---
  restore(Harness, "run", wrapAsync(Harness, "run", "Harness.run()", "malibu-pre"))
  restore(UnifiedProvider, "create", wrapAsync(UnifiedProvider, "create", "UnifiedProvider.create()", "malibu-pre"))
  restore(Skill, "dirs", wrapAsync(Skill, "dirs", "Skill.dirs()", "malibu-pre"))

  // --- Plugin triggers ---
  const pluginStats: CallStats = { count: 0, totalMs: 0, maxMs: 0 }
  restore(Plugin, "trigger", wrapAsyncAccum(Plugin, "trigger", pluginStats))

  // --- DB writes (high-frequency, use accumulator) ---
  const updatePartStats: CallStats = { count: 0, totalMs: 0, maxMs: 0 }
  const updatePartDeltaStats: CallStats = { count: 0, totalMs: 0, maxMs: 0 }
  const updateMessageStats: CallStats = { count: 0, totalMs: 0, maxMs: 0 }
  restore(Session, "updatePart", wrapAsyncAccum(Session, "updatePart", updatePartStats))
  restore(Session, "updatePartDelta", wrapAsyncAccum(Session, "updatePartDelta", updatePartDeltaStats))
  restore(Session, "updateMessage", wrapAsyncAccum(Session, "updateMessage", updateMessageStats))

  // --- MessageV2 fetch ---
  restore(MessageV2, "filterCompacted", wrapAsync(MessageV2, "filterCompacted", "MessageV2.filterCompacted()", "malibu-pre"))

  // --- MALIBU POST-AGENT: harness-processor finalization ---
  restore(Snapshot, "track", wrapAsync(Snapshot, "track", "Snapshot.track()", "malibu-post"))
  restore(Snapshot, "stage", wrapAsync(Snapshot, "stage", "Snapshot.stage()", "malibu-post"))
  restore(Snapshot, "trackFromIndex", wrapAsync(Snapshot, "trackFromIndex", "Snapshot.trackFromIndex()", "malibu-post"))
  restore(Snapshot, "patchFromIndex", wrapAsync(Snapshot, "patchFromIndex", "Snapshot.patchFromIndex()", "malibu-post"))
  restore(Snapshot, "patch", wrapAsync(Snapshot, "patch", "Snapshot.patch()", "malibu-post"))
  restore(SessionSummary, "summarize", wrapAsync(SessionSummary, "summarize", "SessionSummary.summarize()", "malibu-post"))
  restore(SessionCompaction, "prune", wrapAsync(SessionCompaction, "prune", "SessionCompaction.prune()", "malibu-post"))
  restore(SessionCompaction, "isOverflow", wrapAsync(SessionCompaction, "isOverflow", "SessionCompaction.isOverflow()", "malibu-post"))

  return {
    uninstall() {
      for (const [obj, key, orig] of originals) {
        obj[key] = orig
      }
    },
    getStats() {
      return {
        plugin: pluginStats,
        updatePart: updatePartStats,
        updatePartDelta: updatePartDeltaStats,
        updateMessage: updateMessageStats,
      }
    },
  }
}

// ── Benchmark runner ───────────────────────────────────────────────────

async function runBenchmark(
  promptText: string,
  modelOverride?: string,
): Promise<BenchmarkResult & { stats: ReturnType<ReturnType<typeof installGlobalInstrumentation>["getStats"]> }> {
  const timeline: TimelineEntry[] = []
  const textDeltas: TextDeltaRecord[] = []
  const reasoningDeltas: TextDeltaRecord[] = []
  const tools: ToolRecord[] = []
  let tokenUsage: BenchmarkResult["tokenUsage"]
  let sessionID: string | undefined
  let firstTextAfterTool = false
  let lastToolEndTime = 0
  let toolEndCount = 0

  const t0 = performance.now()

  markFn = (label, detail, category = "system") => {
    timeline.push({ time: performance.now() - t0, label, detail, category })
  }

  markFn("Prompt submitted", undefined, "system")

  const instrumentation = installGlobalInstrumentation()
  const unsubs: (() => void)[] = []

  // Harness Bus events
  unsubs.push(Bus.subscribe(Harness.Event.TextDelta, (evt) => {
    if (sessionID && evt.properties.sessionID !== sessionID) return
    const now = performance.now() - t0
    textDeltas.push({ time: now, text: evt.properties.text })
    if (textDeltas.length === 1) {
      markFn("First TextDelta", `"${evt.properties.text.slice(0, 40)}"`, "agent")
    }
    if (firstTextAfterTool && lastToolEndTime > 0) {
      markFn(`First TextDelta after tool #${toolEndCount}`, `gap=${(now - lastToolEndTime).toFixed(1)}ms (2nd LLM TTFT)`, "agent")
      firstTextAfterTool = false
    }
  }))

  unsubs.push(Bus.subscribe(Harness.Event.ReasoningDelta, (evt) => {
    if (sessionID && evt.properties.sessionID !== sessionID) return
    const now = performance.now() - t0
    reasoningDeltas.push({ time: now, text: evt.properties.text })
    if (reasoningDeltas.length === 1) {
      markFn("First ReasoningDelta", `id=${evt.properties.id}`, "agent")
    }
  }))

  unsubs.push(Bus.subscribe(Harness.Event.ToolStart, (evt) => {
    if (sessionID && evt.properties.sessionID !== sessionID) return
    tools.push({ tool: evt.properties.tool, callId: evt.properties.toolCallId, startTime: performance.now() - t0 })
    markFn(`ToolStart: ${evt.properties.tool}`, `callId=${evt.properties.toolCallId}`, "agent")
  }))

  unsubs.push(Bus.subscribe(Harness.Event.ToolEnd, (evt) => {
    if (sessionID && evt.properties.sessionID !== sessionID) return
    const now = performance.now() - t0
    const tool = tools.find((t) => t.callId === evt.properties.toolCallId)
    if (tool) tool.endTime = now
    lastToolEndTime = now
    toolEndCount++
    firstTextAfterTool = true
    markFn(`ToolEnd: ${evt.properties.tool}`, `output="${evt.properties.output.slice(0, 50).replace(/\n/g, "\\n")}"`, "agent")
  }))

  unsubs.push(Bus.subscribe(Harness.Event.StepComplete, (evt) => {
    if (sessionID && evt.properties.sessionID !== sessionID) return
    tokenUsage = evt.properties.tokenUsage
    const u = evt.properties.tokenUsage
    markFn("StepComplete", `in=${u.prompt} out=${u.completion} reason=${u.reasoning} cache_r=${u.cacheRead}`, "agent")
  }))

  unsubs.push(Bus.subscribe(Harness.Event.DoomLoop, (evt) => {
    if (sessionID && evt.properties.sessionID !== sessionID) return
    markFn(`DoomLoop: ${evt.properties.tool}`, `count=${evt.properties.count}`, "agent")
  }))

  // Create session
  markFn("Creating session", undefined, "malibu-pre")
  const session = await Session.create({
    title: "Latency Benchmark",
    permission: [{ permission: "*" as any, pattern: "*", action: "allow" as const }],
  })
  sessionID = session.id
  markFn("Session created", `id=${session.id}`, "malibu-pre")

  const promptInput: any = {
    sessionID: session.id,
    parts: [{ type: "text" as const, text: promptText }],
  }
  if (modelOverride) {
    const [providerID, ...modelParts] = modelOverride.split("/")
    const modelID = modelParts.join("/")
    if (providerID && modelID) promptInput.model = { providerID, modelID }
  }

  markFn("SessionPrompt.prompt() called", undefined, "malibu-pre")
  try {
    await SessionPrompt.prompt(promptInput)
  } catch (err: any) {
    markFn("ERROR", err.message ?? String(err), "system")
  }

  const totalTime = performance.now() - t0
  markFn("Prompt complete", `total=${totalTime.toFixed(1)}ms`, "system")

  const stats = instrumentation.getStats()
  for (const unsub of unsubs) unsub()
  instrumentation.uninstall()

  return { prompt: promptText, model: modelOverride ?? "(default)", timeline, textDeltas, reasoningDeltas, tools, tokenUsage, t0, totalTime, stats }
}

// ── Report ─────────────────────────────────────────────────────────────

const C = {
  pre: "\x1b[33m",   // yellow
  agent: "\x1b[36m", // cyan
  post: "\x1b[35m",  // magenta
  sys: "\x1b[37m",   // white
  dim: "\x1b[2m",    // dim
  bold: "\x1b[1m",   // bold
  reset: "\x1b[0m",
}

const CAT_COLOR: Record<string, string> = { "malibu-pre": C.pre, "agent": C.agent, "malibu-post": C.post, "system": C.sys }
const CAT_LABEL: Record<string, string> = {
  "malibu-pre": "[MALIBU-PRE ]",
  "agent": "[AGENT      ]",
  "malibu-post": "[MALIBU-POST]",
  "system": "[SYSTEM     ]",
}

function printReport(result: BenchmarkResult & { stats: any }, testName?: string) {
  const line = "\u2500".repeat(100)
  const shortLine = "\u2500".repeat(60)

  console.log()
  console.log(`${C.bold}=== Malibu Latency Benchmark${testName ? `: ${testName}` : ""} ===${C.reset}`)
  console.log(`Model: ${result.model}`)
  console.log(`Prompt: "${result.prompt.slice(0, 80)}${result.prompt.length > 80 ? "..." : ""}"`)
  console.log()

  console.log(`${C.bold}LEGEND:${C.reset}`)
  console.log(`  ${C.pre}${CAT_LABEL["malibu-pre"]}${C.reset}  Malibu code BEFORE agent (prompt.ts, harness setup)`)
  console.log(`  ${C.agent}${CAT_LABEL["agent"]}${C.reset}  Inside LangGraph agent (LLM calls, tool execution)`)
  console.log(`  ${C.post}${CAT_LABEL["malibu-post"]}${C.reset}  Malibu code AFTER agent (snapshots, summaries, DB)`)
  console.log()

  // ── FULL TIMELINE ──
  console.log(`${C.bold}FULL TIMELINE:${C.reset}`)
  console.log(line)
  let prev = 0
  for (const entry of result.timeline) {
    const delta = entry.time - prev
    const deltaStr = prev === 0 ? "" : ` (+${delta.toFixed(1)}ms)`
    const timeStr = entry.time.toFixed(1).padStart(10)
    const detail = entry.detail ? ` ${C.dim}\u2014 ${entry.detail}${C.reset}` : ""
    const color = CAT_COLOR[entry.category] ?? ""
    const cat = CAT_LABEL[entry.category] ?? "[?]"
    console.log(`${color}${timeStr}ms ${cat} ${entry.label}${deltaStr}${detail}${C.reset}`)
    prev = entry.time
  }
  console.log()

  // ── PHASE BREAKDOWN ──
  const find = (match: string) => result.timeline.find((e) => e.label.includes(match))?.time
  const findAll = (match: string) => result.timeline.filter((e) => e.label.includes(match)).map((e) => e.time)

  // Key timestamps
  const promptCalled = find("SessionPrompt.prompt() called")
  const harnessRunStart = find("Harness.run() START")
  const harnessRunEnd = find("Harness.run() END")
  const firstContent = find("First ReasoningDelta") ?? find("First TextDelta")
  const firstToolStart = result.timeline.find((e) => e.label.startsWith("ToolStart:"))?.time
  const firstToolEnd = result.timeline.find((e) => e.label.startsWith("ToolEnd:"))?.time
  const stepComplete = find("StepComplete")
  const promptComplete = find("Prompt complete")

  // Snapshot timings
  const snapshotTrackStarts = findAll("Snapshot.track() START")
  const snapshotTrackEnds = findAll("Snapshot.track() END")
  const snapshotPatchStarts = findAll("Snapshot.patch() START")
  const snapshotPatchEnds = findAll("Snapshot.patch() END")

  // === GAP 1: prompt() → first agent output ===
  console.log(`${C.bold}${C.pre}=== GAP 1: prompt() called → first agent output (${firstContent !== undefined && promptCalled !== undefined ? (firstContent - promptCalled).toFixed(0) : "?"}ms) ===${C.reset}`)
  console.log(shortLine)
  if (promptCalled !== undefined) {
    const items: [string, string | undefined][] = []

    // Sub-phases within the gap
    const agentGetStart = find("Agent.get() START")
    const agentGetEnd = find("Agent.get() END")
    const providerGetStart = find("Provider.getModel() START")
    const providerGetEnd = find("Provider.getModel() END")
    const msgFilterStart = findAll("MessageV2.filterCompacted() START")
    const msgFilterEnd = findAll("MessageV2.filterCompacted() END")
    const toolRegStart = find("ToolRegistry.all() START")
    const toolRegEnd = find("ToolRegistry.all() END")
    const mcpStart = find("MCP.tools() START")
    const mcpEnd = find("MCP.tools() END")
    const syspromptStart = find("SystemPrompt.environment() START")
    const syspromptEnd = find("SystemPrompt.environment() END")
    const skillsPromptStart = find("SystemPrompt.skills() START")
    const skillsPromptEnd = find("SystemPrompt.skills() END")
    const instrStart = find("InstructionPrompt.system() START")
    const instrEnd = find("InstructionPrompt.system() END")
    const providerCreateStart = find("UnifiedProvider.create() START")
    const providerCreateEnd = find("UnifiedProvider.create() END")
    const skillDirsStart = find("Skill.dirs() START")
    const skillDirsEnd = find("Skill.dirs() END")

    items.push(["", undefined])
    items.push(["MALIBU CODE (before Harness.run):", undefined])

    if (msgFilterStart.length > 0 && msgFilterEnd.length > 0) {
      items.push(["  MessageV2.filterCompacted() [fetch all messages]", `${(msgFilterEnd[0] - msgFilterStart[0]).toFixed(1)}ms`])
    }
    if (agentGetStart !== undefined && agentGetEnd !== undefined) {
      items.push(["  Agent.get() [resolve agent config]", `${(agentGetEnd - agentGetStart).toFixed(1)}ms`])
    }
    if (providerGetStart !== undefined && providerGetEnd !== undefined) {
      items.push(["  Provider.getModel() [resolve model]", `${(providerGetEnd - providerGetStart).toFixed(1)}ms`])
    }
    if (toolRegStart !== undefined && toolRegEnd !== undefined) {
      items.push(["  ToolRegistry.all() [load all tools]", `${(toolRegEnd - toolRegStart).toFixed(1)}ms`])
    }
    if (mcpStart !== undefined && mcpEnd !== undefined) {
      items.push(["  MCP.tools() [load MCP tools]", `${(mcpEnd - mcpStart).toFixed(1)}ms`])
    }
    if (syspromptStart !== undefined && syspromptEnd !== undefined) {
      items.push(["  SystemPrompt.environment() [build system prompt]", `${(syspromptEnd - syspromptStart).toFixed(1)}ms`])
    }
    if (skillsPromptStart !== undefined && skillsPromptEnd !== undefined) {
      items.push(["  SystemPrompt.skills() [load skills prompt]", `${(skillsPromptEnd - skillsPromptStart).toFixed(1)}ms`])
    }
    if (instrStart !== undefined && instrEnd !== undefined) {
      items.push(["  InstructionPrompt.system() [CLAUDE.md etc]", `${(instrEnd - instrStart).toFixed(1)}ms`])
    }
    // Pre-exec snapshot
    if (snapshotTrackStarts.length > 0 && snapshotTrackEnds.length > 0) {
      items.push(["  Snapshot.track() [pre-exec git status]", `${(snapshotTrackEnds[0] - snapshotTrackStarts[0]).toFixed(1)}ms`])
    }

    // Total Malibu pre
    if (harnessRunStart !== undefined) {
      items.push(["  SUBTOTAL: Malibu before Harness.run()", `${(harnessRunStart - promptCalled).toFixed(1)}ms`])
    }

    items.push(["", undefined])
    items.push(["INSIDE Harness.run() — buildAgentConfig:", undefined])

    if (providerCreateStart !== undefined && providerCreateEnd !== undefined) {
      items.push(["  UnifiedProvider.create() [create ChatModel]", `${(providerCreateEnd - providerCreateStart).toFixed(1)}ms`])
    }
    if (skillDirsStart !== undefined && skillDirsEnd !== undefined) {
      items.push(["  Skill.dirs() [find skill directories]", `${(skillDirsEnd - skillDirsStart).toFixed(1)}ms`])
    }

    // Estimate: from Harness.run START to first agent output = agent build + LLM TTFT
    if (harnessRunStart !== undefined && firstContent !== undefined) {
      items.push(["  SUBTOTAL: Harness.run() → first output", `${(firstContent - harnessRunStart).toFixed(1)}ms`])
      items.push(["    (includes: tool conversion, middleware assembly,", undefined])
      items.push(["     agent.stream() HTTP request, LLM inference TTFT)", undefined])
    }

    // Total GAP 1
    if (firstContent !== undefined) {
      items.push(["", undefined])
      items.push(["  TOTAL GAP 1", `${(firstContent - promptCalled).toFixed(1)}ms`])
    }

    for (const [label, value] of items) {
      if (value === undefined) {
        console.log(`  ${C.pre}${label}${C.reset}`)
      } else {
        console.log(`  ${label.padEnd(55)}${C.bold}${value}${C.reset}`)
      }
    }
  }
  console.log()

  // === GAP 2: ToolEnd → next TextDelta ===
  const textAfterTool = result.timeline.find((e) => e.label.startsWith("First TextDelta after tool"))
  if (textAfterTool && firstToolEnd !== undefined) {
    console.log(`${C.bold}${C.agent}=== GAP 2: ToolEnd → next TextDelta (${(textAfterTool.time - firstToolEnd).toFixed(0)}ms) ===${C.reset}`)
    console.log(shortLine)
    console.log(`  This is the 2nd LLM API call TTFT.`)
    console.log(`  After the tool completes, LangGraph feeds the result`)
    console.log(`  back to the LLM as a ToolMessage. The LLM must:`)
    console.log(`    1. Receive new HTTP request with tool result`)
    console.log(`    2. Process all context (${result.tokenUsage?.prompt ?? "?"} prompt tokens)`)
    console.log(`    3. Generate first response token`)
    console.log(`  Total: ${C.bold}${(textAfterTool.time - firstToolEnd).toFixed(1)}ms${C.reset}`)
    console.log()
  }

  // === GAP 3: StepComplete → Prompt complete ===
  if (stepComplete !== undefined && promptComplete !== undefined) {
    const gap3 = promptComplete - stepComplete
    console.log(`${C.bold}${C.post}=== GAP 3: StepComplete → Prompt complete (${gap3.toFixed(0)}ms) ===${C.reset}`)
    console.log(shortLine)

    const items: [string, string | undefined][] = []

    items.push(["", undefined])
    items.push(["POST-PROCESSING (harness-processor.ts processOnce):", undefined])
    items.push(["  After the LangGraph stream ends:", undefined])

    // Post-exec snapshot (second call)
    if (snapshotTrackStarts.length > 1 && snapshotTrackEnds.length > 1) {
      items.push(["  Snapshot.track() [post-exec git status]", `${(snapshotTrackEnds[1] - snapshotTrackStarts[1]).toFixed(1)}ms`])
    }
    if (snapshotPatchStarts.length > 0 && snapshotPatchEnds.length > 0) {
      items.push(["  Snapshot.patch() [compute git diff]", `${(snapshotPatchEnds[0] - snapshotPatchStarts[0]).toFixed(1)}ms`])
    }

    const summarizeStart = find("SessionSummary.summarize() START")
    const summarizeEnd = find("SessionSummary.summarize() END")
    if (summarizeStart !== undefined && summarizeEnd !== undefined) {
      items.push(["  SessionSummary.summarize() [git diffs + title LLM call]", `${(summarizeEnd - summarizeStart).toFixed(1)}ms`])
    } else if (summarizeStart !== undefined) {
      items.push(["  SessionSummary.summarize() [fire-and-forget, still running]", "not awaited"])
    }

    const overflowStart = find("SessionCompaction.isOverflow() START")
    const overflowEnd = find("SessionCompaction.isOverflow() END")
    if (overflowStart !== undefined && overflowEnd !== undefined) {
      items.push(["  SessionCompaction.isOverflow()", `${(overflowEnd - overflowStart).toFixed(1)}ms`])
    }

    if (harnessRunEnd !== undefined && stepComplete !== undefined) {
      items.push(["  SUBTOTAL: StepComplete → Harness.run() return", `${(harnessRunEnd - stepComplete).toFixed(1)}ms`])
    }

    items.push(["", undefined])
    items.push(["LOOP EXIT (prompt.ts loop):", undefined])
    items.push(["  After Harness.run returns, the loop:", undefined])
    items.push(["    1. Checks finish status", undefined])
    items.push(["    2. Re-fetches ALL messages (MessageV2.filterCompacted)", undefined])
    items.push(["    3. Scans for lastAssistant.finish → breaks", undefined])
    items.push(["    4. SessionCompaction.prune()", undefined])
    items.push(["    5. MessageV2.stream() to find result", undefined])

    // Second MessageV2.filterCompacted (loop re-iteration)
    if (msgFilterSecondCall(result)) {
      items.push(["  MessageV2.filterCompacted() [2nd call, re-fetch]", msgFilterSecondCall(result)!])
    }

    const pruneStart = find("SessionCompaction.prune() START")
    const pruneEnd = find("SessionCompaction.prune() END")
    if (pruneStart !== undefined && pruneEnd !== undefined) {
      items.push(["  SessionCompaction.prune()", `${(pruneEnd - pruneStart).toFixed(1)}ms`])
    }

    if (harnessRunEnd !== undefined && promptComplete !== undefined) {
      items.push(["  SUBTOTAL: Harness.run() return → prompt complete", `${(promptComplete - harnessRunEnd).toFixed(1)}ms`])
    }

    items.push(["", undefined])
    items.push(["  TOTAL GAP 3", `${gap3.toFixed(1)}ms`])

    for (const [label, value] of items) {
      if (value === undefined) {
        console.log(`  ${C.post}${label}${C.reset}`)
      } else {
        console.log(`  ${label.padEnd(55)}${C.bold}${value}${C.reset}`)
      }
    }
  }
  console.log()

  // ── DB / PLUGIN STATS ──
  console.log(`${C.bold}HIGH-FREQUENCY OPERATION STATS:${C.reset}`)
  console.log(shortLine)
  const s = result.stats
  console.log(`  Session.updatePart():      ${s.updatePart.count} calls, total=${s.updatePart.totalMs.toFixed(1)}ms, avg=${s.updatePart.count ? (s.updatePart.totalMs / s.updatePart.count).toFixed(1) : 0}ms, max=${s.updatePart.maxMs.toFixed(1)}ms`)
  console.log(`  Session.updatePartDelta():  ${s.updatePartDelta.count} calls, total=${s.updatePartDelta.totalMs.toFixed(1)}ms, avg=${s.updatePartDelta.count ? (s.updatePartDelta.totalMs / s.updatePartDelta.count).toFixed(1) : 0}ms, max=${s.updatePartDelta.maxMs.toFixed(1)}ms`)
  console.log(`  Session.updateMessage():    ${s.updateMessage.count} calls, total=${s.updateMessage.totalMs.toFixed(1)}ms, avg=${s.updateMessage.count ? (s.updateMessage.totalMs / s.updateMessage.count).toFixed(1) : 0}ms, max=${s.updateMessage.maxMs.toFixed(1)}ms`)
  console.log(`  Plugin.trigger():           ${s.plugin.count} calls, total=${s.plugin.totalMs.toFixed(1)}ms, avg=${s.plugin.count ? (s.plugin.totalMs / s.plugin.count).toFixed(1) : 0}ms, max=${s.plugin.maxMs.toFixed(1)}ms`)
  console.log()

  // ── WHERE DID THE TIME GO? ──
  const malibuPreTime = (harnessRunStart ?? promptCalled ?? 0) - 0
  const agentTime = (stepComplete ?? harnessRunEnd ?? 0) - (harnessRunStart ?? 0)
  const postAgentTime = (promptComplete ?? result.totalTime) - (stepComplete ?? harnessRunEnd ?? 0)
  const total = result.totalTime

  if (total > 0) {
    console.log(`${C.bold}WHERE DID THE TIME GO?${C.reset}`)
    console.log(shortLine)
    const barW = 40
    const bar = (ms: number) => {
      const n = Math.max(0, Math.round((ms / total) * barW))
      return "\u2588".repeat(n) + " ".repeat(barW - n)
    }
    console.log(`  ${C.pre}Malibu pre-agent:  ${bar(malibuPreTime)} ${malibuPreTime.toFixed(0)}ms (${((malibuPreTime / total) * 100).toFixed(1)}%)${C.reset}`)
    console.log(`  ${C.agent}Agent (LangGraph):  ${bar(agentTime)} ${agentTime.toFixed(0)}ms (${((agentTime / total) * 100).toFixed(1)}%)${C.reset}`)
    console.log(`  ${C.post}Malibu post-agent: ${bar(postAgentTime)} ${postAgentTime.toFixed(0)}ms (${((postAgentTime / total) * 100).toFixed(1)}%)${C.reset}`)
    console.log(`  ${C.bold}Total:              ${" ".repeat(barW)} ${total.toFixed(0)}ms${C.reset}`)
  }
  console.log()

  // Token usage
  if (result.tokenUsage) {
    console.log(`${C.bold}TOKEN USAGE:${C.reset}`)
    console.log(shortLine)
    const u = result.tokenUsage
    console.log(`  Prompt: ${u.prompt}  Completion: ${u.completion}  Reasoning: ${u.reasoning}  Cache read: ${u.cacheRead}  Cache write: ${u.cacheWrite}`)
    console.log()
  }

  // Token streaming
  if (result.textDeltas.length > 1) {
    console.log(`${C.bold}TOKEN STREAMING:${C.reset}`)
    console.log(shortLine)
    const gaps: number[] = []
    for (let i = 1; i < result.textDeltas.length; i++) gaps.push(result.textDeltas[i].time - result.textDeltas[i - 1].time)
    const avg = gaps.reduce((a, b) => a + b, 0) / gaps.length
    const max = Math.max(...gaps)
    const min = Math.min(...gaps)
    const dur = result.textDeltas[result.textDeltas.length - 1].time - result.textDeltas[0].time
    const tps = dur > 0 ? (result.textDeltas.length / dur) * 1000 : 0
    console.log(`  Deltas: ${result.textDeltas.length}  Duration: ${dur.toFixed(0)}ms  Avg gap: ${avg.toFixed(1)}ms  Max: ${max.toFixed(1)}ms  Min: ${min.toFixed(1)}ms  Throughput: ${tps.toFixed(0)}/s`)
    console.log()
  }
}

/** Find the 2nd MessageV2.filterCompacted call timing (loop re-iteration) */
function msgFilterSecondCall(result: BenchmarkResult): string | undefined {
  const starts = result.timeline.filter((e) => e.label === "MessageV2.filterCompacted() START")
  const ends = result.timeline.filter((e) => e.label === "MessageV2.filterCompacted() END")
  if (starts.length >= 2 && ends.length >= 2) {
    return `${(ends[1].time - starts[1].time).toFixed(1)}ms`
  }
  return undefined
}

function printComparison(results: { name: string; result: BenchmarkResult & { stats: any } }[]) {
  const line = "\u2500".repeat(100)
  console.log()
  console.log(`${C.bold}=== COMPARISON ===${C.reset}`)
  console.log(line)

  const headers = ["Test", "Total", "Malibu Pre", "Agent", "Malibu Post", "TTFT", "Tools", "DB writes"]
  const rows: string[][] = []

  for (const { name, result } of results) {
    const f = (m: string) => result.timeline.find((e) => e.label.includes(m))?.time
    const hStart = f("Harness.run() START") ?? 0
    const sc = f("StepComplete") ?? f("Harness.run() END") ?? 0
    const pc = f("Prompt complete") ?? result.totalTime
    const promptC = f("prompt() called") ?? 0
    const fc = f("First ReasoningDelta") ?? f("First TextDelta")
    const ttft = fc !== undefined ? `${(fc - promptC).toFixed(0)}ms` : "N/A"
    const dbCalls = result.stats.updatePart.count + result.stats.updatePartDelta.count + result.stats.updateMessage.count
    rows.push([name, `${result.totalTime.toFixed(0)}ms`, `${hStart.toFixed(0)}ms`, `${(sc - hStart).toFixed(0)}ms`, `${(pc - sc).toFixed(0)}ms`, ttft, String(result.tools.length), String(dbCalls)])
  }

  const colW = headers.map((h, i) => Math.max(h.length, ...rows.map((r) => r[i].length)))
  console.log(headers.map((h, i) => h.padEnd(colW[i])).join("  "))
  console.log(colW.map((w) => "\u2500".repeat(w)).join("  "))
  for (const row of rows) console.log(row.map((c, i) => c.padEnd(colW[i])).join("  "))
  console.log()
}

// ── Main ───────────────────────────────────────────────────────────────

async function main() {
  const args = parseArgs()
  await Log.init({ print: false, level: "WARN" })

  console.log("Booting Malibu instance...")
  const startBoot = performance.now()

  try {
    await Instance.provide({
      directory: process.cwd(),
      init: InstanceBootstrap,
      fn: async () => {
        await Config.waitForDependencies()
        await ToolRegistry.ids()
        console.log(`Instance booted in ${(performance.now() - startBoot).toFixed(0)}ms\n`)

        if (args.all) {
          const results: { name: string; result: BenchmarkResult & { stats: any } }[] = []
          for (const [, test] of Object.entries(TEST_PROMPTS)) {
            console.log(`\u2501\u2501\u2501 Running: ${test.name} \u2501\u2501\u2501`)
            const result = await runBenchmark(test.prompt, args.model)
            printReport(result, test.name)
            results.push({ name: test.name, result })
          }
          printComparison(results)
        } else if (args.test) {
          const test = TEST_PROMPTS[args.test]
          if (!test) { console.error(`Unknown test: ${args.test}. Available: ${Object.keys(TEST_PROMPTS).join(", ")}`); process.exit(1) }
          console.log(`Running: ${test.name} — ${test.description}`)
          const result = await runBenchmark(test.prompt, args.model)
          printReport(result, test.name)
        } else {
          const prompt = args.prompt ?? TEST_PROMPTS.bash.prompt
          console.log(`Running benchmark...`)
          const result = await runBenchmark(prompt, args.model)
          printReport(result)
        }
      },
    })
  } finally {
    await Instance.disposeAll().catch(() => {})
  }
}

main().catch((err) => { console.error("Benchmark failed:", err); process.exit(1) })
