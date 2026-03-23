/**
 * Standalone Agent Test — Bypasses OpenCode/Malibu entirely.
 *
 * This script creates a createAgent() ReactAgent DIRECTLY with a REAL LLM,
 * real tools, and streams the full conversation to see if the agent
 * keeps going or stops after 2-3 tool calls.
 *
 * If the agent stops here too → it's a model/prompt issue.
 * If the agent keeps going here but stops in OpenCode → it's OpenCode's architecture.
 *
 * Run:
 *   cd packages/opencode
 *   ANTHROPIC_API_KEY=sk-... bun test test/agent/standalone-agent.test.ts --timeout 300000
 *
 * Output:
 *   test/agent/output/standalone-agent-trace.md
 */
import { describe, test, afterAll, beforeAll } from "bun:test"
import fs from "fs/promises"
import path from "path"
import { readFileSync } from "fs"

// Load .env from project root (handles Windows \r line endings)
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
    // Strip surrounding quotes
    if ((val.startsWith("'") && val.endsWith("'")) || (val.startsWith('"') && val.endsWith('"'))) {
      val = val.slice(1, -1)
    }
    if (val && !process.env[key]) {
      process.env[key] = val
    }
  }
} catch {
  // .env not found — rely on shell env
}
// @ts-expect-error — tsgo browser condition misses agent exports
import { createAgent } from "langchain"
import { ChatAnthropic } from "@langchain/anthropic"
import { ChatOpenAI } from "@langchain/openai"
import { DynamicStructuredTool } from "@langchain/core/tools"
import { AIMessageChunk, ToolMessage, AIMessage, HumanMessage } from "@langchain/core/messages"
import { z } from "zod"

// ---------------------------------------------------------------------------
// Output collection
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
// Create REAL tools (simple versions, no Malibu dependencies)
// ---------------------------------------------------------------------------

const listTool = new DynamicStructuredTool({
  name: "list",
  description: "List files and directories at the given path. Use to explore directory structure.",
  schema: z.object({
    path: z.string().optional().describe("Directory path to list. Defaults to current directory."),
  }),
  async func({ path: dirPath }) {
    const target = dirPath || process.cwd()
    try {
      const entries = await fs.readdir(target, { withFileTypes: true })
      const result = entries
        .slice(0, 30)
        .map((e) => (e.isDirectory() ? e.name + "/" : e.name))
        .join("\n")
      return result || "Empty directory"
    } catch (err: any) {
      return `Error: ${err.message}`
    }
  },
})

const readTool = new DynamicStructuredTool({
  name: "read",
  description: "Read the contents of a file. Returns the file text with line numbers.",
  schema: z.object({
    filePath: z.string().describe("Path to the file to read"),
    limit: z.number().optional().describe("Max lines to read (default 100)"),
  }),
  async func({ filePath, limit }) {
    try {
      const content = await fs.readFile(filePath, "utf-8")
      const lines = content.split("\n").slice(0, limit ?? 100)
      return lines.map((l, i) => `${i + 1}: ${l}`).join("\n") || "(empty file)"
    } catch (err: any) {
      return `Error: ${err.message}`
    }
  },
})

const globTool = new DynamicStructuredTool({
  name: "glob",
  description: "Find files matching a glob pattern. Returns matching file paths.",
  schema: z.object({
    pattern: z.string().describe("Glob pattern like **/*.ts or src/**/*.js"),
    path: z.string().optional().describe("Directory to search in"),
  }),
  async func({ pattern, path: searchPath }) {
    const { Glob } = await import("bun")
    const target = searchPath || "."
    const glob = new Glob(pattern)
    const results: string[] = []
    for await (const file of glob.scan({ cwd: target, dot: false })) {
      results.push(file)
      if (results.length >= 30) break
    }
    return results.join("\n") || "No files found"
  },
})

const grepTool = new DynamicStructuredTool({
  name: "grep",
  description: "Search file contents for a regex pattern. Returns matching file paths.",
  schema: z.object({
    pattern: z.string().describe("Regex pattern to search for"),
    path: z.string().optional().describe("Directory to search in"),
    include: z.string().optional().describe("File glob filter like *.ts"),
  }),
  async func({ pattern, path: searchPath, include }) {
    try {
      const args = ["rg", "--files-with-matches", "--no-heading", "-e", pattern]
      if (include) args.push("--glob", include)
      args.push(searchPath || ".")
      const proc = Bun.spawn(args, { stdout: "pipe", stderr: "pipe" })
      const text = await new Response(proc.stdout).text()
      return text.trim().split("\n").slice(0, 20).join("\n") || "No matches"
    } catch {
      return "No matches (or rg not available)"
    }
  },
})

const bashTool = new DynamicStructuredTool({
  name: "bash",
  description: "Run a shell command and return its output.",
  schema: z.object({
    command: z.string().describe("The shell command to execute"),
    description: z.string().describe("Brief description of what this command does"),
  }),
  async func({ command, description }) {
    try {
      const proc = Bun.spawn(["bash", "-c", command], {
        stdout: "pipe",
        stderr: "pipe",
        cwd: process.cwd(),
      })
      const stdout = await new Response(proc.stdout).text()
      const stderr = await new Response(proc.stderr).text()
      const exitCode = await proc.exited
      if (exitCode !== 0 && stderr) return `Exit ${exitCode}:\n${stderr}\n${stdout}`
      return stdout.trim() || "(no output)"
    } catch (err: any) {
      return `Error: ${err.message}`
    }
  },
})

const tools = [listTool, readTool, globTool, grepTool, bashTool]

// ---------------------------------------------------------------------------
// Create the LLM — uses env var for API key
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
    return new ChatOpenAI({
      model: "gpt-4o",
      apiKey: openaiKey,
      maxTokens: 4096,
      streaming: true,
    })
  }

  throw new Error(
    "No API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable.",
  )
}

// ---------------------------------------------------------------------------
// Stream and trace the agent execution
// ---------------------------------------------------------------------------

async function runAgent(prompt: string, systemPrompt: string, label: string) {
  logSection(label)
  log(`**Prompt:** ${prompt}`)
  log(`**System (first 200 chars):** ${systemPrompt.slice(0, 200)}...`)
  log("")

  const model = createLLM()
  const startTime = performance.now()

  const agent = createAgent({
    model,
    tools,
    systemPrompt,
    name: "standalone-test",
  }).withConfig({
    recursionLimit: 100,
  })

  const threadId = `standalone-${Date.now()}`
  let stepCount = 0
  let toolCallCount = 0
  let textChunks = 0

  try {
    const stream = await agent.stream(
      { messages: [new HumanMessage(prompt)] },
      {
        configurable: { thread_id: threadId },
        streamMode: "messages",
      },
    )

    // Accumulate tool_call_chunks to get full args
    // (streaming sends args incrementally — tool_calls on individual chunks have empty {})
    const pendingChunks = new Map<string, { name: string; argsJson: string; logged: boolean }>()

    for await (const event of stream) {
      const [msg] = Array.isArray(event) ? event : [event]
      const elapsed = Math.round(performance.now() - startTime)

      if (msg instanceof AIMessageChunk) {
        // Extract text from both string and array content blocks
        let content = ""
        if (typeof msg.content === "string") {
          content = msg.content
        } else if (Array.isArray(msg.content)) {
          content = msg.content
            .map((p: any) => typeof p === "string" ? p : (p.type === "text" ? p.text : ""))
            .filter(Boolean).join("")
        }

        // Text output (no limit — log all text to see the complete final answer)
        if (content && content.trim()) {
          textChunks++
          log(`[T+${String(elapsed).padStart(6)}ms] TEXT: ${content.slice(0, 300)}`)
        }

        // Accumulate tool_call_chunks by INDEX (not ID — subsequent chunks have id=undefined)
        // First chunk has: id=toolu_xxx, name="read", args="", index=1
        // Subsequent:      id=undefined, name=undefined, args='{"filePath"', index=1
        for (const chunk of msg.tool_call_chunks ?? []) {
          const idx = String(chunk.index ?? 0)
          if (chunk.id) {
            // First chunk with real ID — create entry keyed by both ID and index
            pendingChunks.set(chunk.id, { name: chunk.name ?? "", argsJson: "", logged: false })
            pendingChunks.set(`_idx_${idx}`, { name: chunk.name ?? "", argsJson: "", logged: false })
          }
          // Accumulate args by index (works for all chunks including id=undefined ones)
          const byIdx = pendingChunks.get(`_idx_${idx}`)
          if (byIdx) byIdx.argsJson += chunk.args ?? ""
        }

        // Map real tool_call IDs to index-accumulated args
        for (const tc of msg.tool_calls ?? []) {
          const id = tc.id ?? tc.name
          if (!pendingChunks.has(id)) {
            pendingChunks.set(id, { name: tc.name, argsJson: JSON.stringify(tc.args), logged: false })
          }
        }
      } else if (msg instanceof ToolMessage) {
        const toolCallId = (msg as any).tool_call_id ?? ""

        // Find the pending entry (by real ID) and its accumulated args (by index)
        const pending = pendingChunks.get(toolCallId)
        if (pending && !pending.logged) {
          toolCallCount++
          stepCount++
          // Find the index-based accumulator that has the actual args
          let argsJson = pending.argsJson
          for (const [key, val] of pendingChunks) {
            if (key.startsWith("_idx_") && val.name === pending.name && val.argsJson) {
              argsJson = val.argsJson
              pendingChunks.delete(key)
              break
            }
          }
          let parsedArgs: any = {}
          try { parsedArgs = JSON.parse(argsJson) } catch { parsedArgs = { _raw: argsJson.slice(0, 200) } }
          const argsStr = JSON.stringify(parsedArgs).slice(0, 250)
          log(`[T+${String(elapsed).padStart(6)}ms] TOOL_CALL #${toolCallCount}: ${pending.name}(${argsStr})`)
          pending.logged = true
        }

        const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)
        const preview = content.slice(0, 200).replace(/\n/g, "\\n")
        log(`[T+${String(elapsed).padStart(6)}ms] TOOL_RESULT [${msg.name}]: ${preview}`)
        pendingChunks.delete(toolCallId)
      } else if (msg instanceof AIMessage) {
        // Full AIMessage (non-chunk) — may contain the final text response
        const content = typeof msg.content === "string" ? msg.content
          : Array.isArray(msg.content) ? msg.content.map((p: any) => typeof p === "string" ? p : p.text ?? "").join("")
          : ""
        if (content && content.trim()) {
          textChunks++
          log(`[T+${String(elapsed).padStart(6)}ms] AI_MESSAGE (full): ${content.slice(0, 500)}`)
        }
        if (msg.tool_calls?.length) {
          log(`[T+${String(elapsed).padStart(6)}ms] AI_MESSAGE has ${msg.tool_calls.length} tool_calls`)
        }
      } else {
        // Unknown message type — log it to catch anything we're missing
        const msgType = msg?.constructor?.name ?? typeof msg
        const msgContent = typeof msg?.content === "string" ? msg.content.slice(0, 100) : ""
        if (msgContent) {
          log(`[T+${String(elapsed).padStart(6)}ms] OTHER[${msgType}]: ${msgContent}`)
        }
      }
    }

    const streamEnd = Math.round(performance.now() - startTime)
    log(`[T+${String(streamEnd).padStart(6)}ms] === STREAM ENDED ===`)
  } catch (err: any) {
    log(`[ERROR] ${err.name}: ${err.message}`)
    log(`Stack: ${err.stack?.split("\n").slice(0, 5).join("\n")}`)
  }

  const totalTime = Math.round(performance.now() - startTime)
  log("")
  log(`### Summary`)
  log(`- Total time: ${totalTime}ms`)
  log(`- Tool calls: ${toolCallCount}`)
  log(`- Text chunks: ${textChunks}`)
  log(`- Steps: ${stepCount}`)
  log("")
}

// ---------------------------------------------------------------------------
// Write output
// ---------------------------------------------------------------------------

afterAll(async () => {
  const outputPath = path.join(import.meta.dir, "output", "standalone-agent-trace.md")
  await fs.mkdir(path.dirname(outputPath), { recursive: true })

  const header = [
    "# Standalone Agent Trace — Direct createAgent() Test",
    `Generated: ${new Date().toISOString()}`,
    "",
    "This test bypasses OpenCode/Malibu entirely.",
    "It creates a `createAgent()` ReactAgent directly with a real LLM and real tools.",
    "If the agent stops after 2-3 tools here → model/prompt issue.",
    "If it keeps going here but stops in OpenCode → OpenCode architecture issue.",
    "",
    "---",
    "",
  ].join("\n")

  await fs.writeFile(outputPath, header + outputLines.join("\n"), "utf-8")
  console.log(`\nTrace written to: ${outputPath}`)
})

// ===========================================================================
// Tests
// ===========================================================================

describe("Standalone Agent — Direct createAgent", () => {

  // Test 1: Minimal prompt, NO "keep going" instruction
  test("Test 1: Minimal prompt — does the agent keep going?", async () => {
    await runAgent(
      "Explore this codebase. List the top-level files, then read the package.json, then tell me what this project is about.",
      "You are a helpful coding assistant. Use the available tools to help the user.",
      "Test 1: Minimal system prompt (no keep-going instruction)",
    )
  }, 120_000)

  // Test 2: With explicit "keep going" instruction
  test("Test 2: With keep-going instruction", async () => {
    await runAgent(
      "Explore this codebase. List the top-level files, then read the package.json, then tell me what this project is about.",
      [
        "You are a helpful coding assistant. Use the available tools to help the user.",
        "",
        "IMPORTANT: You are an agent. Keep going until the user's query is COMPLETELY resolved.",
        "Do NOT stop after one or two tool calls. If you need more information, keep calling tools.",
        "Only stop when you have fully answered the user's question with all the details they asked for.",
      ].join("\n"),
      "Test 2: With explicit keep-going instruction",
    )
  }, 120_000)

  // Test 3: With the ACTUAL anthropic.txt prompt (the one used in production)
  test("Test 3: With actual Malibu anthropic.txt prompt", async () => {
    const promptPath = path.join(import.meta.dir, "../../src/session/prompt/anthropic.txt")
    const toolRefPath = path.join(import.meta.dir, "../../src/session/prompt/tool-reference.txt")
    let systemPrompt: string
    try {
      const main = await fs.readFile(promptPath, "utf-8")
      const toolRef = await fs.readFile(toolRefPath, "utf-8")
      systemPrompt = main + "\n" + toolRef
    } catch {
      systemPrompt = "You are a helpful coding assistant."
      log("(Could not load anthropic.txt — using fallback)")
    }

    await runAgent(
      "Explore this codebase. List the top-level files, then read the package.json, then tell me what this project is about.",
      systemPrompt,
      "Test 3: Actual Malibu anthropic.txt + tool-reference.txt prompt",
    )
  }, 120_000)

  // Test 4: Multi-step task that REQUIRES many tool calls
  test("Test 4: Multi-step task requiring many tools", async () => {
    await runAgent(
      "I need you to do the following: 1) List the files in the current directory, 2) Read package.json, 3) Find all TypeScript files matching **/*.test.ts, 4) Read the first test file you find, 5) Run 'git log --oneline -5' to see recent commits. Do ALL of these steps.",
      [
        "You are a helpful coding assistant.",
        "You MUST complete ALL steps the user asks for. Do not stop early.",
        "Keep calling tools until every step is done, then summarize your findings.",
      ].join("\n"),
      "Test 4: Explicit 5-step task — does agent complete all 5?",
    )
  }, 120_000)

})
