/**
 * Agent Loop Diagnostic — WHY does the agent stop?
 *
 * Runs the SAME prompt through THREE setups to isolate the problem:
 *   1. Raw createAgent() — pure LangChain, no Malibu
 *   2. createMalibuAgent() — Malibu wrapper with middleware
 *   3. Old harness simulation — the outer "continue" loop that was the bug
 *
 * If createAgent keeps going but createMalibuAgent stops → middleware issue.
 * If both keep going but harness stops → harness outer loop issue.
 * If all three stop → model/prompt issue.
 *
 * Run:
 *   cd packages/opencode
 *   ANTHROPIC_API_KEY=sk-... bun test test/agent/agent-loop-diagnostic.test.ts --timeout 300000
 *
 * Output:
 *   test/agent/output/agent-loop-diagnostic.md
 */
import { describe, test, afterAll } from "bun:test"
import fs from "fs/promises"
import path from "path"
import { readFileSync } from "fs"

// Load .env from project root
const envPath = path.join(import.meta.dir, "../../../../.env")
try {
  const envContent = readFileSync(envPath, "utf-8")
  for (const line of envContent.split("\n")) {
    const clean = line.replace(/\r$/, "").trim()
    if (!clean || clean.startsWith("#")) continue
    const eq = clean.indexOf("=")
    if (eq === -1) continue
    const key = clean.slice(0, eq)
    let val = clean.slice(eq + 1)
    if ((val.startsWith("'") && val.endsWith("'")) || (val.startsWith('"') && val.endsWith('"'))) {
      val = val.slice(1, -1)
    }
    if (val && !process.env[key]) process.env[key] = val
  }
} catch { /* .env not found */ }

// @ts-expect-error — tsgo browser condition misses agent exports
import { createAgent } from "langchain"
import { ChatAnthropic } from "@langchain/anthropic"
import { ChatOpenAI } from "@langchain/openai"
import { DynamicStructuredTool } from "@langchain/core/tools"
import { AIMessageChunk, ToolMessage, AIMessage, HumanMessage, BaseMessage } from "@langchain/core/messages"
import { LocalShellBackend } from "deepagents"
import { z } from "zod"
import { createMalibuAgent } from "../../src/agent/create-agent"

// ---------------------------------------------------------------------------
// Simple logging
// ---------------------------------------------------------------------------

const outputLines: string[] = []

function log(line: string) {
  outputLines.push(line)
  console.log(line)
}

function logSection(title: string) {
  log("")
  log("=".repeat(80))
  log(`## ${title}`)
  log("=".repeat(80))
  log("")
}

// ---------------------------------------------------------------------------
// Real tools (no Malibu deps, just filesystem)
// ---------------------------------------------------------------------------

const listTool = new DynamicStructuredTool({
  name: "list",
  description: "List files and directories at the given path.",
  schema: z.object({
    path: z.string().optional().describe("Directory path to list"),
  }),
  async func({ path: dirPath }) {
    const target = dirPath || process.cwd()
    try {
      const entries = await fs.readdir(target, { withFileTypes: true })
      return entries.slice(0, 30).map(e => e.isDirectory() ? e.name + "/" : e.name).join("\n") || "Empty"
    } catch (err: any) { return `Error: ${err.message}` }
  },
})

const readTool = new DynamicStructuredTool({
  name: "read",
  description: "Read a file's contents with line numbers.",
  schema: z.object({
    filePath: z.string().describe("Path to the file"),
    limit: z.number().optional().describe("Max lines (default 100)"),
  }),
  async func({ filePath, limit }) {
    try {
      const content = await fs.readFile(filePath, "utf-8")
      const lines = content.split("\n").slice(0, limit ?? 100)
      return lines.map((l, i) => `${i + 1}: ${l}`).join("\n") || "(empty)"
    } catch (err: any) { return `Error: ${err.message}` }
  },
})

const globTool = new DynamicStructuredTool({
  name: "glob",
  description: "Find files matching a glob pattern.",
  schema: z.object({
    pattern: z.string().describe("Glob pattern like **/*.ts"),
    path: z.string().optional().describe("Directory to search in"),
  }),
  async func({ pattern, path: searchPath }) {
    const { Glob } = await import("bun")
    const glob = new Glob(pattern)
    const results: string[] = []
    for await (const file of glob.scan({ cwd: searchPath || ".", dot: false })) {
      results.push(file)
      if (results.length >= 30) break
    }
    return results.join("\n") || "No files found"
  },
})

const grepTool = new DynamicStructuredTool({
  name: "grep",
  description: "Search file contents for a regex pattern.",
  schema: z.object({
    pattern: z.string().describe("Regex pattern to search for"),
    path: z.string().optional().describe("Directory to search in"),
  }),
  async func({ pattern, path: searchPath }) {
    try {
      const proc = Bun.spawn(["rg", "--files-with-matches", "-e", pattern, searchPath || "."], { stdout: "pipe", stderr: "pipe" })
      const text = await new Response(proc.stdout).text()
      return text.trim().split("\n").slice(0, 20).join("\n") || "No matches"
    } catch { return "No matches" }
  },
})

const bashTool = new DynamicStructuredTool({
  name: "bash",
  description: "Run a shell command.",
  schema: z.object({
    command: z.string().describe("The command to execute"),
  }),
  async func({ command }) {
    try {
      const proc = Bun.spawn(["bash", "-c", command], { stdout: "pipe", stderr: "pipe", cwd: process.cwd() })
      const stdout = await new Response(proc.stdout).text()
      const stderr = await new Response(proc.stderr).text()
      const code = await proc.exited
      if (code !== 0 && stderr) return `Exit ${code}:\n${stderr}\n${stdout}`
      return stdout.trim() || "(no output)"
    } catch (err: any) { return `Error: ${err.message}` }
  },
})

const tools = [listTool, readTool, globTool, grepTool, bashTool]

// ---------------------------------------------------------------------------
// LLM setup
// ---------------------------------------------------------------------------

function createLLM() {
  const anthropicKey = process.env.ANTHROPIC_API_KEY
  const openaiKey = process.env.OPENAI_API_KEY

  if (anthropicKey) {
    log("Using: ChatAnthropic (claude-sonnet-4-20250514)")
    return new ChatAnthropic({
      model: "claude-sonnet-4-20250514",
      apiKey: anthropicKey,
      maxTokens: 4096,
      streaming: true,
    })
  }
  if (openaiKey) {
    log("Using: ChatOpenAI (gpt-4o)")
    return new ChatOpenAI({ model: "gpt-4o", apiKey: openaiKey, maxTokens: 4096, streaming: true })
  }
  throw new Error("No API key. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.")
}

// ---------------------------------------------------------------------------
// Stream consumer — logs every tool call, result, and text
// ---------------------------------------------------------------------------

interface RunResult {
  toolCallCount: number
  textChunks: number
  responseText: string
  toolCalls: Array<{ name: string; id: string; args: any; output: string }>
}

async function streamAndLog(
  stream: AsyncIterable<any>,
  startTime: number,
): Promise<RunResult> {
  const result: RunResult = { toolCallCount: 0, textChunks: 0, responseText: "", toolCalls: [] }
  const pending = new Map<string, { name: string; argsJson: string; logged: boolean }>()

  for await (const event of stream) {
    const [msg] = Array.isArray(event) ? event : [event]
    const elapsed = Math.round(performance.now() - startTime)
    const ts = `[T+${String(elapsed).padStart(6)}ms]`

    if (msg instanceof AIMessageChunk) {
      // Text
      let content = ""
      if (typeof msg.content === "string") content = msg.content
      else if (Array.isArray(msg.content)) {
        content = msg.content.map((p: any) => typeof p === "string" ? p : p.type === "text" ? p.text : "").filter(Boolean).join("")
      }
      if (content?.trim()) {
        result.textChunks++
        result.responseText += content
        log(`${ts} TEXT: ${content.slice(0, 300)}`)
      }

      // Tool call chunks (accumulate args)
      for (const chunk of msg.tool_call_chunks ?? []) {
        const idx = String(chunk.index ?? 0)
        if (chunk.id) {
          pending.set(chunk.id, { name: chunk.name ?? "", argsJson: "", logged: false })
          pending.set(`_idx_${idx}`, { name: chunk.name ?? "", argsJson: "", logged: false })
        }
        const byIdx = pending.get(`_idx_${idx}`)
        if (byIdx) byIdx.argsJson += chunk.args ?? ""
      }

      // Complete tool_calls
      for (const tc of msg.tool_calls ?? []) {
        const id = tc.id ?? tc.name
        if (!pending.has(id)) {
          pending.set(id, { name: tc.name, argsJson: JSON.stringify(tc.args), logged: false })
        }
      }

    } else if (msg instanceof ToolMessage) {
      const toolCallId = (msg as any).tool_call_id ?? ""
      const p = pending.get(toolCallId)
      if (p && !p.logged) {
        result.toolCallCount++
        // Find accumulated args
        let argsJson = p.argsJson
        for (const [key, val] of pending) {
          if (key.startsWith("_idx_") && val.name === p.name && val.argsJson) {
            argsJson = val.argsJson
            pending.delete(key)
            break
          }
        }
        let args: any = {}
        try { args = JSON.parse(argsJson) } catch { args = { _raw: argsJson.slice(0, 200) } }
        log(`${ts} TOOL #${result.toolCallCount}: ${p.name}(${JSON.stringify(args).slice(0, 250)})`)
        p.logged = true
        result.toolCalls.push({ name: p.name, id: toolCallId, args, output: "" })
      }

      const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)
      const preview = content.slice(0, 200).replace(/\n/g, "\\n")
      log(`${ts} RESULT [${msg.name}]: ${preview}`)
      const tc = result.toolCalls.find(t => t.id === toolCallId)
      if (tc) tc.output = content
      pending.delete(toolCallId)

    } else if (msg instanceof AIMessage) {
      const content = typeof msg.content === "string" ? msg.content
        : Array.isArray(msg.content) ? msg.content.map((p: any) => typeof p === "string" ? p : p.text ?? "").join("") : ""
      if (content?.trim()) {
        result.textChunks++
        result.responseText += content
        log(`${ts} AI_MESSAGE: ${content.slice(0, 500)}`)
      }
    }
  }

  const elapsed = Math.round(performance.now() - startTime)
  log(`[T+${String(elapsed).padStart(6)}ms] === STREAM ENDED ===`)
  return result
}

// ---------------------------------------------------------------------------
// The prompt — requires exactly 5 tool calls to complete
// ---------------------------------------------------------------------------

const TASK_PROMPT = [
  "Do ALL of these steps in order:",
  "1) List the files in the current directory",
  "2) Read package.json",
  "3) Find all TypeScript files matching src/**/*.ts",
  "4) Read the first file you find from step 3",
  "5) Run 'git log --oneline -5' to see recent commits",
  "",
  "Complete ALL 5 steps, then summarize what you learned.",
].join("\n")

const SYSTEM_PROMPT = [
  "You are a helpful coding assistant.",
  "You MUST complete ALL steps the user asks for. Do not stop early.",
  "Keep calling tools until every step is done, then summarize your findings.",
].join("\n")

// ===========================================================================
// Tests
// ===========================================================================

describe("Agent Loop Diagnostic", () => {

  // -----------------------------------------------------------------------
  // Test 1: Raw createAgent — pure LangChain, no Malibu wrapper
  // -----------------------------------------------------------------------
  test("1. Raw createAgent — does the ReAct loop complete all 5 steps?", async () => {
    logSection("Test 1: Raw createAgent (pure LangChain)")
    log(`Prompt: ${TASK_PROMPT.split("\n")[0]}...`)
    log("")

    const model = createLLM()
    const start = performance.now()

    const agent = createAgent({
      model,
      tools,
      systemPrompt: SYSTEM_PROMPT,
    }).withConfig({ recursionLimit: 100 })

    const stream = await agent.stream(
      { messages: [new HumanMessage(TASK_PROMPT)] },
      { configurable: { thread_id: "raw-" + Date.now() }, streamMode: "messages" },
    )

    const result = await streamAndLog(stream, start)
    const elapsed = Math.round(performance.now() - start)

    log("")
    log("### Summary (Raw createAgent)")
    log(`- Time: ${elapsed}ms`)
    log(`- Tool calls: ${result.toolCallCount}`)
    log(`- Text chunks: ${result.textChunks}`)
    log(`- Tools used: ${result.toolCalls.map(t => t.name).join(", ")}`)
    log(`- Old harness would return: ${result.toolCallCount > 0 ? '"continue" (BUG — would re-invoke)' : '"stop"'}`)
    log(`- New harness returns: "stop" (correct — loop ran internally)`)
    log("")
  }, 120_000)

  // -----------------------------------------------------------------------
  // Test 2: createMalibuAgent — same test, with Malibu middleware
  // -----------------------------------------------------------------------
  test("2. createMalibuAgent — does the middleware break anything?", async () => {
    logSection("Test 2: createMalibuAgent (Malibu wrapper + middleware)")
    log(`Prompt: ${TASK_PROMPT.split("\n")[0]}...`)
    log("")

    const model = createLLM()
    const start = performance.now()

    const tmpPath = path.join(import.meta.dir, "output", "tmp-malibu-diag")
    await fs.mkdir(tmpPath, { recursive: true })

    const agent = createMalibuAgent({
      model,
      tools,
      systemPrompt: SYSTEM_PROMPT,
      checkpointer: false,
      backend: new LocalShellBackend({ rootDir: tmpPath }),
      subagents: [],
      name: "diag-agent",
      isAnthropicModel: !!process.env.ANTHROPIC_API_KEY,
    })

    const stream = await agent.stream(
      { messages: [new HumanMessage(TASK_PROMPT)] },
      { configurable: { thread_id: "malibu-" + Date.now() }, streamMode: "messages" },
    )

    const result = await streamAndLog(stream, start)
    const elapsed = Math.round(performance.now() - start)

    log("")
    log("### Summary (createMalibuAgent)")
    log(`- Time: ${elapsed}ms`)
    log(`- Tool calls: ${result.toolCallCount}`)
    log(`- Text chunks: ${result.textChunks}`)
    log(`- Tools used: ${result.toolCalls.map(t => t.name).join(", ")}`)
    log("")

    await fs.rm(tmpPath, { recursive: true, force: true }).catch(() => {})
  }, 120_000)

  // -----------------------------------------------------------------------
  // Test 3: Old harness behavior — simulate the "continue if tools > 0" loop
  // -----------------------------------------------------------------------
  test("3. Old harness simulation — how many wasted iterations?", async () => {
    logSection("Test 3: Old Harness Simulation (continue if toolCalls > 0)")
    log("Simulates the OLD bug: outer loop keeps re-invoking if any tools were called.")
    log("")

    const model = createLLM()
    const start = performance.now()
    let outerIteration = 0
    let totalToolCalls = 0
    let totalModelCalls = 0

    // Build message history like the old session loop did
    const messageHistory: BaseMessage[] = [new HumanMessage(TASK_PROMPT)]

    while (outerIteration < 5) { // safety cap
      outerIteration++
      log(`--- Outer loop iteration #${outerIteration} ---`)

      const agent = createAgent({
        model,
        tools,
        systemPrompt: SYSTEM_PROMPT,
      }).withConfig({ recursionLimit: 100 })

      const stream = await agent.stream(
        { messages: [...messageHistory] },
        { configurable: { thread_id: `old-iter${outerIteration}-${Date.now()}` }, streamMode: "messages" },
      )

      const result = await streamAndLog(stream, start)
      totalToolCalls += result.toolCallCount
      totalModelCalls++

      // OLD LOGIC: continue if tools were called
      const oldStatus = result.toolCallCount > 0 ? "continue" : "stop"
      log(`>>> Old harness status: "${oldStatus}" (${result.toolCallCount} tool calls this iteration)`)

      if (oldStatus === "stop") {
        log(">>> Outer loop STOPPED (no tool calls)")
        break
      }

      // Feed results back into history for next iteration
      if (result.toolCalls.length > 0) {
        messageHistory.push(new AIMessage({
          content: result.responseText,
          tool_calls: result.toolCalls.map(tc => ({ id: tc.id, name: tc.name, args: tc.args })),
        }))
        for (const tc of result.toolCalls) {
          messageHistory.push(new ToolMessage({
            tool_call_id: tc.id,
            name: tc.name,
            content: tc.output,
          }))
        }
      }
      log("")
    }

    const elapsed = Math.round(performance.now() - start)

    log("")
    log("### Summary (Old Harness)")
    log(`- Time: ${elapsed}ms`)
    log(`- Outer loop iterations: ${outerIteration}`)
    log(`- Total tool calls across all iterations: ${totalToolCalls}`)
    log(`- API calls to model: ${totalModelCalls} (each is a full stream)`)
    log(`- Wasted iterations: ${outerIteration - 1}`)
    log(`- Wasted tool calls: ${totalToolCalls - (totalToolCalls / outerIteration | 0)}`)
    log("")
    if (outerIteration > 1) {
      log("^^^ THIS IS THE BUG. The old harness re-invoked the agent because")
      log("    toolCalls.length > 0, even though the agent already finished.")
      log("    The fix: always return 'stop' — the internal ReAct loop handles continuation.")
    }
    log("")
  }, 300_000)

  // -----------------------------------------------------------------------
  // Test 4: New harness behavior — single invocation, always stop
  // -----------------------------------------------------------------------
  test("4. New harness behavior — single invocation", async () => {
    logSection("Test 4: New Harness (always stop after stream)")
    log("This is what the FIX does: one stream() call, always return 'stop'.")
    log("")

    const model = createLLM()
    const start = performance.now()

    const agent = createAgent({
      model,
      tools,
      systemPrompt: SYSTEM_PROMPT,
    }).withConfig({ recursionLimit: 100 })

    const stream = await agent.stream(
      { messages: [new HumanMessage(TASK_PROMPT)] },
      { configurable: { thread_id: "new-" + Date.now() }, streamMode: "messages" },
    )

    const result = await streamAndLog(stream, start)
    const elapsed = Math.round(performance.now() - start)

    log("")
    log("### Summary (New Harness)")
    log(`- Time: ${elapsed}ms`)
    log(`- Outer loop iterations: 1 (always)`)
    log(`- Tool calls: ${result.toolCallCount}`)
    log(`- Status returned: "stop" (always — internal loop handles continuation)`)
    log(`- Tools used: ${result.toolCalls.map(t => t.name).join(", ")}`)
    log("")
  }, 120_000)

  // -----------------------------------------------------------------------
  // Write output
  // -----------------------------------------------------------------------
  afterAll(async () => {
    const outputPath = path.join(import.meta.dir, "output", "agent-loop-diagnostic.md")
    await fs.mkdir(path.dirname(outputPath), { recursive: true })

    const header = [
      "# Agent Loop Diagnostic",
      `Generated: ${new Date().toISOString()}`,
      "",
      "Tests the SAME 5-step prompt through different agent setups to isolate",
      "where the premature stopping happens.",
      "",
      "- **Test 1**: Raw createAgent (pure LangChain) — baseline",
      "- **Test 2**: createMalibuAgent (Malibu wrapper) — does middleware break it?",
      "- **Test 3**: Old harness simulation — the 'continue if tools > 0' bug",
      "- **Test 4**: New harness (always stop) — the fix",
      "",
      "---",
      "",
    ].join("\n")

    await fs.writeFile(outputPath, header + outputLines.join("\n"), "utf-8")
    console.log(`\nDiagnostic written to: ${outputPath}`)
  })
})
