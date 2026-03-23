#!/usr/bin/env bun
/**
 * Sub-Agent Parallel Execution Diagnostic Script — REAL MODEL VERSION
 *
 * Uses real LLM API keys from ../../.env to test parallel sub-agent execution
 * with actual model calls. This exposes timing-dependent bugs that don't
 * reproduce with fake models.
 *
 * Run:
 *   cd packages/opencode && bun run test/agent/subagent-diagnostic.ts
 *
 * Output:
 *   test/agent/subagent-diagnostic-output.md
 */

// --- Load .env from project root ---
import os from "os"
import path from "path"
import fs from "fs/promises"

// Load .env file manually (before any other imports)
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
    // Strip quotes (handle inline comments after quoted values)
    if (value.startsWith("'")) {
      const endQuote = value.indexOf("'", 1)
      if (endQuote !== -1) value = value.slice(1, endQuote)
    } else if (value.startsWith('"')) {
      const endQuote = value.indexOf('"', 1)
      if (endQuote !== -1) value = value.slice(1, endQuote)
    } else {
      // Unquoted: strip inline comments
      const commentIdx = value.indexOf("#")
      if (commentIdx !== -1) value = value.slice(0, commentIdx).trim()
    }
    if (value) process.env[key] = value
  }
  console.log("Loaded .env from:", envPath)
  // Clear base URL env vars — ChatOpenAI auto-reads them and the .env has a comment-laden one
  delete process.env.OPENAI_BASE_URL
  delete process.env.OPENAI_API_BASE
  console.log("OPENAI_API_KEY:", process.env.OPENAI_API_KEY ? `${process.env.OPENAI_API_KEY.slice(0, 12)}...` : "NOT SET")
  console.log("ANTHROPIC_API_KEY:", process.env.ANTHROPIC_API_KEY ? `${process.env.ANTHROPIC_API_KEY.slice(0, 12)}...` : "NOT SET")
} catch (e: any) {
  console.error("Failed to load .env:", e.message)
  process.exit(1)
}

// --- Environment setup (must happen before any src/ imports) ---
const tmpBase = path.join(os.tmpdir(), "malibu-diag-" + Date.now())
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

// --- Preload langchain resolver ---
await import("../../script/preload-langchain")

// --- Now safe to import from src/ ---
const { Log } = await import("../../src/util/log")
Log.init({ print: true, dev: true, level: "INFO" })

import { AIMessage, AIMessageChunk, HumanMessage, ToolMessage, BaseMessage } from "@langchain/core/messages"
import { DynamicStructuredTool } from "@langchain/core/tools"
import { z } from "zod"
import { ChatOpenAI } from "@langchain/openai"
import {
  createSubAgentMiddleware,
  LocalShellBackend,
} from "deepagents"
import type { SubAgent } from "deepagents"
import { createMalibuAgent } from "../../src/agent/create-agent"

// ---------------------------------------------------------------------------
// Diagnostic types
// ---------------------------------------------------------------------------

interface DiagnosticEntry {
  time: number
  elapsed: number
  type: string
  details: Record<string, any>
}

interface ToolCallTrace {
  id: string
  name: string
  args: any
  startMs: number
  endMs?: number
  result?: string
  error?: string
}

// ---------------------------------------------------------------------------
// Main diagnostic
// ---------------------------------------------------------------------------

async function runDiagnostic() {
  const log: DiagnosticEntry[] = []
  const toolTraces: ToolCallTrace[] = []
  const globalStart = performance.now()
  let crashed = false
  let crashError: Error | null = null

  function entry(type: string, details: Record<string, any> = {}) {
    const now = performance.now()
    log.push({
      time: Date.now(),
      elapsed: Math.round(now - globalStart),
      type,
      details,
    })
  }

  // --- Create git repo in tmpdir ---
  const repoDir = path.join(tmpBase, "repo")
  await fs.mkdir(repoDir, { recursive: true })
  // Create a simple file for agents to read
  await fs.writeFile(path.join(repoDir, "README.md"), "# Test Repo\nThis is a test repo for diagnostics.\n")
  await fs.mkdir(path.join(repoDir, "src"), { recursive: true })
  await fs.writeFile(path.join(repoDir, "src", "index.ts"), "export function hello() { return 'world' }\n")
  await fs.writeFile(path.join(repoDir, "src", "utils.ts"), "export function add(a: number, b: number) { return a + b }\n")

  const { $ } = await import("bun")
  await $`git init`.cwd(repoDir).quiet()
  await $`git config core.fsmonitor false`.cwd(repoDir).quiet()
  await $`git config user.email "diag@test"`.cwd(repoDir).quiet()
  await $`git config user.name "Diag"`.cwd(repoDir).quiet()
  await $`git add -A`.cwd(repoDir).quiet()
  await $`git commit -m "init"`.cwd(repoDir).quiet()

  entry("setup_complete", { repoDir, tmpBase })

  // --- Build the agent with REAL models ---
  console.log("\n=== Building agent with REAL OpenAI model ===")
  console.log("Model: gpt-4o-mini (cheapest for testing)")
  console.log("Sub-agents: explore, general (both gpt-4o-mini)")

  // Use gpt-4o-mini — cheapest model with tool calling support
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

  // Create dummy tools that simulate real tool execution
  const searchTool = new DynamicStructuredTool({
    name: "search_code",
    description: "Search for patterns in the codebase",
    schema: z.object({
      pattern: z.string().describe("The pattern to search for"),
      path: z.string().optional().describe("Directory to search in"),
    }),
    func: async ({ pattern, path: searchPath }) => {
      await new Promise(r => setTimeout(r, 100)) // Simulate I/O
      return `Found 3 matches for "${pattern}" in ${searchPath ?? "."}: src/index.ts:1, src/utils.ts:1, README.md:1`
    },
  })

  const readFileTool = new DynamicStructuredTool({
    name: "read_file",
    description: "Read a file from the filesystem",
    schema: z.object({
      path: z.string().describe("Path to the file to read"),
    }),
    func: async ({ path: filePath }) => {
      await new Promise(r => setTimeout(r, 50))
      return `Contents of ${filePath}:\nexport function hello() { return 'world' }`
    },
  })

  const explore: SubAgent = {
    name: "explore",
    description: "Fast agent for exploring codebases. Use for searching files, reading code, and answering questions.",
    systemPrompt: "You are an explore agent. Use the search_code and read_file tools to explore the codebase. Be brief (under 100 words).",
    model: subagentModel,
    tools: [searchTool, readFileTool],
  }

  const general: SubAgent = {
    name: "general",
    description: "General-purpose agent for multi-step tasks.",
    systemPrompt: "You are a general agent. Use the search_code tool to find information. Be brief (under 100 words).",
    model: subagentModel,
    tools: [searchTool],
  }

  const backend = new LocalShellBackend({ rootDir: repoDir })

  let agent: ReturnType<typeof createMalibuAgent>
  try {
    agent = createMalibuAgent({
      model,
      tools: [], // No tools for parent — only the task tool from middleware
      systemPrompt: `You are a helpful coding assistant. You MUST use the task tool to delegate work to sub-agents.

IMPORTANT: When asked to explore, you MUST call the task tool TWICE in PARALLEL in the same response:
1. First call: task(description="Explore the project structure", subagent_type="explore")
2. Second call: task(description="Analyze the codebase patterns", subagent_type="explore")

Call both tools in the SAME message (parallel tool calls). Do NOT call them sequentially.
After receiving both results, provide a brief summary.`,
      checkpointer: false,
      backend,
      subagents: [explore, general],
      name: "diag-agent",
      isAnthropicModel: false,
    })
    entry("agent_created")
    console.log("Agent created successfully.\n")
  } catch (error: any) {
    entry("agent_creation_error", { message: error.message, stack: error.stack })
    console.error("FATAL: Agent creation failed:", error.message)
    crashed = true
    crashError = error
    await writeReport(log, toolTraces, crashed, crashError)
    process.exit(1)
  }

  // --- Stream the agent ---
  console.log("=== Streaming agent with REAL API calls ===")
  console.log("Prompt: 'Please explore this codebase. Deploy 2 explore agents in parallel.'\n")

  const threadId = "diag-real-" + Date.now()
  const streamStart = performance.now()

  try {
    const stream = await agent.stream(
      { messages: [new HumanMessage("Please explore this codebase. Deploy 2 explore agents in parallel to look at different aspects.")] },
      {
        configurable: { thread_id: threadId },
        streamMode: "messages",
      },
    )

    let eventIndex = 0
    for await (const event of stream) {
      eventIndex++
      const [msg, metadata] = Array.isArray(event) ? event : [event, undefined]

      if (msg instanceof AIMessageChunk) {
        const content = typeof msg.content === "string" ? msg.content : ""
        const contentArr = Array.isArray(msg.content) ? msg.content : []

        if (content) {
          entry("AIMessageChunk:text", { text: content.slice(0, 300) })
          if (content.length > 1) { // Skip single-char streaming chunks in console
            process.stdout.write(content)
          }
        }
        for (const part of contentArr) {
          const p = part as any
          if (p.type === "text" && p.text) {
            entry("AIMessageChunk:text_block", { text: p.text.slice(0, 300) })
            process.stdout.write(p.text)
          } else if (p.type === "thinking" && p.thinking) {
            entry("AIMessageChunk:thinking", { text: p.thinking.slice(0, 300) })
          }
        }

        for (const tc of msg.tool_call_chunks ?? []) {
          entry("AIMessageChunk:tool_call_chunk", {
            id: tc.id,
            name: tc.name,
            args: tc.args?.slice(0, 200),
            index: tc.index,
          })
          if (tc.name && tc.id) {
            console.log(`\n  [TOOL_CALL_CHUNK] ${tc.name} (${tc.id})`)
            toolTraces.push({
              id: tc.id,
              name: tc.name,
              args: tc.args,
              startMs: Math.round(performance.now() - streamStart),
            })
          }
        }

        for (const tc of msg.tool_calls ?? []) {
          entry("AIMessageChunk:tool_call", {
            id: tc.id,
            name: tc.name,
            args: tc.args,
          })
          console.log(`\n  [TOOL_CALL] ${tc.name} (${tc.id}) args=${JSON.stringify(tc.args).slice(0, 100)}`)
          const existing = toolTraces.find((t) => t.id === tc.id)
          if (!existing) {
            toolTraces.push({
              id: tc.id ?? "unknown",
              name: tc.name,
              args: tc.args,
              startMs: Math.round(performance.now() - streamStart),
            })
          }
        }

        const usage = (msg as any).usage_metadata
        if (usage) {
          entry("AIMessageChunk:usage", {
            input_tokens: usage.input_tokens,
            output_tokens: usage.output_tokens,
          })
        }
      } else if (msg instanceof ToolMessage) {
        const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)
        const toolCallId = (msg as any).tool_call_id ?? ""
        entry("ToolMessage", {
          tool_call_id: toolCallId,
          name: msg.name,
          content: content.slice(0, 500),
        })

        const trace = toolTraces.find((t) => t.id === toolCallId)
        if (trace) {
          trace.endMs = Math.round(performance.now() - streamStart)
          trace.result = content.slice(0, 500)
        }

        console.log(`\n  [TOOL_RESULT] ${msg.name} (${toolCallId}) — ${content.slice(0, 120)}`)
      } else if (msg instanceof AIMessage) {
        const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)
        entry("AIMessage", {
          content: content.slice(0, 500),
          tool_calls: msg.tool_calls?.map((tc) => ({ id: tc.id, name: tc.name })),
        })
        if (msg.tool_calls && msg.tool_calls.length > 0) {
          console.log(`\n  [AI_MSG] tool_calls: ${msg.tool_calls.map(tc => `${tc.name}(${tc.id})`).join(", ")}`)
        } else if (content) {
          process.stdout.write(content)
        }
      } else {
        entry("OtherMessage", {
          constructor: msg?.constructor?.name,
          content: JSON.stringify(msg).slice(0, 200),
        })
      }
    }

    entry("stream_complete", { totalEvents: eventIndex })
    console.log(`\n\n=== Stream completed: ${eventIndex} events ===`)

  } catch (error: any) {
    crashed = true
    crashError = error
    entry("stream_crash", {
      message: error.message,
      name: error.name,
      stack: error.stack,
    })
    console.error("\n\n=== STREAM CRASHED ===")
    console.error("Error:", error.message)
    console.error("Name:", error.name)
    console.error("Stack:", error.stack)
  }

  // --- Write report ---
  await writeReport(log, toolTraces, crashed, crashError)

  // --- Cleanup ---
  try {
    await fs.rm(tmpBase, { recursive: true, force: true })
  } catch {
    // Ignore cleanup errors
  }

  if (crashed) {
    console.error("\n[RESULT] CRASHED — see diagnostic output for details")
  } else {
    console.log("\n[RESULT] SUCCESS — stream completed without crash")

    // Print summary
    const toolCalls = toolTraces.filter(t => t.name === "task")
    const completed = toolCalls.filter(t => t.endMs != null)
    const orphaned = toolCalls.filter(t => t.endMs == null)
    console.log(`\nTask tool calls: ${toolCalls.length}`)
    console.log(`  Completed: ${completed.length}`)
    console.log(`  Orphaned (no ToolMessage): ${orphaned.length}`)
    if (orphaned.length > 0) {
      console.log("  Note: Orphaned task calls are expected — SubAgentMiddleware returns")
      console.log("  Command objects with embedded ToolMessages that don't stream separately.")
    }
  }

  return crashed
}

// ---------------------------------------------------------------------------
// Report writer
// ---------------------------------------------------------------------------

async function writeReport(
  log: DiagnosticEntry[],
  toolTraces: ToolCallTrace[],
  crashed: boolean,
  crashError: Error | null,
  filename = "subagent-diagnostic-output.md",
  subtitle = "No Checkpointer",
) {
  const outputPath = path.join(import.meta.dir, filename)
  const lines: string[] = []

  lines.push(`# Sub-Agent Parallel Execution Diagnostic Report (${subtitle})`)
  lines.push(`Generated: ${new Date().toISOString()}`)
  lines.push(`Status: ${crashed ? "**CRASHED**" : "**SUCCESS**"}`)
  lines.push("")

  lines.push("## Configuration")
  lines.push("- Parent model: `gpt-4o-mini` (OpenAI, streaming)")
  lines.push("- Sub-agents: explore (gpt-4o-mini), general (gpt-4o-mini)")
  lines.push("- Checkpointer: disabled (false)")
  lines.push("- Sub-agent tools: none (text-only responses)")
  lines.push("- Stream mode: `messages`")
  lines.push("")

  lines.push("## Event Timeline")
  lines.push("")
  lines.push("| Time (ms) | Event Type | Details |")
  lines.push("|-----------|-----------|---------|")

  for (const entry of log) {
    const time = String(entry.elapsed).padStart(6)
    const type = entry.type
    let details = ""

    if (entry.details.message) {
      details = entry.details.message
    } else if (entry.details.text) {
      details = entry.details.text.slice(0, 80)
    } else if (entry.details.id) {
      details = `id=${entry.details.id} name=${entry.details.name ?? "?"}`
      if (entry.details.args) {
        const argsStr = typeof entry.details.args === "string"
          ? entry.details.args
          : JSON.stringify(entry.details.args)
        details += ` args=${argsStr.slice(0, 60)}`
      }
    } else if (entry.details.tool_call_id) {
      details = `tool_call_id=${entry.details.tool_call_id} name=${entry.details.name}`
      if (entry.details.content) details += ` content=${entry.details.content.slice(0, 60)}`
    } else if (entry.details.content) {
      details = entry.details.content.slice(0, 80)
    } else {
      details = JSON.stringify(entry.details).slice(0, 80)
    }

    details = details.replace(/\|/g, "\\|").replace(/\n/g, " ")
    lines.push(`| ${time} | ${type} | ${details} |`)
  }
  lines.push("")

  if (toolTraces.length > 0) {
    lines.push("## Tool Call Traces")
    lines.push("")

    for (const trace of toolTraces) {
      lines.push(`### ${trace.name} (${trace.id})`)
      lines.push(`- **Started**: ${trace.startMs}ms`)
      if (trace.endMs != null) {
        lines.push(`- **Completed**: ${trace.endMs}ms (duration: ${trace.endMs - trace.startMs}ms)`)
      } else {
        lines.push("- **Completed**: NEVER (orphaned — Command-embedded ToolMessage)")
      }
      lines.push(`- **Args**: \`${typeof trace.args === "string" ? trace.args : JSON.stringify(trace.args)}\``)
      if (trace.result) {
        lines.push(`- **Result**: ${trace.result.slice(0, 300)}`)
      }
      if (trace.error) {
        lines.push(`- **Error**: ${trace.error}`)
      }
      lines.push("")
    }
  }

  if (crashed && crashError) {
    lines.push("## Crash Details")
    lines.push("")
    lines.push("```")
    lines.push(`Error: ${crashError.message}`)
    lines.push(`Name: ${crashError.name}`)
    lines.push("")
    lines.push("Stack trace:")
    lines.push(crashError.stack ?? "No stack trace available")
    lines.push("```")
    lines.push("")
  }

  const errorEntries = log.filter((e) => e.type.includes("error") || e.type.includes("crash"))
  if (errorEntries.length > 0) {
    lines.push("## All Errors")
    lines.push("")
    for (const entry of errorEntries) {
      lines.push(`### ${entry.type} (${entry.elapsed}ms)`)
      lines.push("```")
      lines.push(JSON.stringify(entry.details, null, 2))
      lines.push("```")
      lines.push("")
    }
  }

  lines.push("## Summary")
  lines.push("")
  lines.push(`- Total events: ${log.length}`)
  lines.push(`- Tool call traces: ${toolTraces.length}`)
  lines.push(`- Completed tool calls: ${toolTraces.filter((t) => t.endMs != null).length}`)
  lines.push(`- Orphaned tool calls: ${toolTraces.filter((t) => t.endMs == null).length}`)
  lines.push(`- Errors in log: ${errorEntries.length}`)
  lines.push(`- Final status: ${crashed ? "CRASHED" : "SUCCESS"}`)
  lines.push("")

  const content = lines.join("\n")
  await fs.writeFile(outputPath, content, "utf-8")
  console.log(`\nDiagnostic report written to: ${outputPath}`)
}

// ---------------------------------------------------------------------------
// Test 2: With SQLite checkpointer
// ---------------------------------------------------------------------------

async function runDiagnosticWithCheckpointer() {
  const log2: DiagnosticEntry[] = []
  const toolTraces2: ToolCallTrace[] = []
  const globalStart2 = performance.now()
  let crashed2 = false
  let crashError2: Error | null = null

  function entry2(type: string, details: Record<string, any> = {}) {
    const now = performance.now()
    log2.push({ time: Date.now(), elapsed: Math.round(now - globalStart2), type, details })
  }

  // Setup
  const tmpBase2 = path.join(os.tmpdir(), "malibu-diag-ckpt-" + Date.now())
  await fs.mkdir(tmpBase2, { recursive: true })
  const repoDir2 = path.join(tmpBase2, "repo")
  await fs.mkdir(repoDir2, { recursive: true })
  await fs.writeFile(path.join(repoDir2, "README.md"), "# Test Repo\n")
  await fs.mkdir(path.join(repoDir2, "src"), { recursive: true })
  await fs.writeFile(path.join(repoDir2, "src", "index.ts"), "export function hello() { return 'world' }\n")

  const { $ } = await import("bun")
  await $`git init`.cwd(repoDir2).quiet()
  await $`git config core.fsmonitor false`.cwd(repoDir2).quiet()
  await $`git config user.email "diag@test"`.cwd(repoDir2).quiet()
  await $`git config user.name "Diag"`.cwd(repoDir2).quiet()
  await $`git add -A`.cwd(repoDir2).quiet()
  await $`git commit -m "init"`.cwd(repoDir2).quiet()

  entry2("setup_complete", { repoDir: repoDir2 })

  // Use the REAL SqliteCheckpointer — same as production
  const { SqliteCheckpointer } = await import("../../src/agent/checkpointer")
  const dbPath = path.join(tmpBase2, "langgraph-checkpoints.db")
  const checkpointer = new SqliteCheckpointer(dbPath)
  console.log("Using SqliteCheckpointer at:", dbPath)

  const model2 = new ChatOpenAI({
    modelName: "gpt-4o-mini",
    temperature: 0,
    streaming: true,
    apiKey: process.env.OPENAI_API_KEY,
  })

  const subModel2 = new ChatOpenAI({
    modelName: "gpt-4o-mini",
    temperature: 0,
    streaming: true,
    apiKey: process.env.OPENAI_API_KEY,
  })

  const searchTool2 = new DynamicStructuredTool({
    name: "search_code",
    description: "Search for patterns in the codebase",
    schema: z.object({ pattern: z.string(), path: z.string().optional() }),
    func: async ({ pattern, path: p }) => {
      await new Promise(r => setTimeout(r, 100))
      return `Found 3 matches for "${pattern}" in ${p ?? "."}`
    },
  })

  const readFileTool2 = new DynamicStructuredTool({
    name: "read_file",
    description: "Read a file from the filesystem",
    schema: z.object({ path: z.string() }),
    func: async ({ path: p }) => {
      await new Promise(r => setTimeout(r, 50))
      return `Contents of ${p}:\nexport function hello() { return 'world' }`
    },
  })

  const explore2: SubAgent = {
    name: "explore",
    description: "Fast agent for exploring codebases.",
    systemPrompt: "You are an explore agent. Use search_code and read_file tools. Respond briefly (under 100 words).",
    model: subModel2,
    tools: [searchTool2, readFileTool2],
  }

  const general2: SubAgent = {
    name: "general",
    description: "General-purpose agent.",
    systemPrompt: "You are a general agent. Use search_code tool. Respond briefly (under 100 words).",
    model: subModel2,
    tools: [searchTool2],
  }

  const backend2 = new LocalShellBackend({ rootDir: repoDir2 })

  let agent2: ReturnType<typeof createMalibuAgent>
  try {
    agent2 = createMalibuAgent({
      model: model2,
      tools: [],
      systemPrompt: `You are a helpful coding assistant. You MUST use the task tool to delegate work to sub-agents.
IMPORTANT: Call the task tool TWICE in PARALLEL in the same response:
1. task(description="Explore the project structure", subagent_type="explore")
2. task(description="Analyze the codebase patterns", subagent_type="explore")
Call both in the SAME message. After receiving both results, provide a brief summary.`,
      checkpointer,
      backend: backend2,
      subagents: [explore2, general2],
      name: "diag-agent-ckpt",
      isAnthropicModel: false,
    })
    entry2("agent_created")
    console.log("Agent with checkpointer created successfully.\n")
  } catch (error: any) {
    entry2("agent_creation_error", { message: error.message, stack: error.stack })
    console.error("FATAL: Agent creation failed:", error.message)
    crashed2 = true
    crashError2 = error
    await writeReport(log2, toolTraces2, crashed2, crashError2, "subagent-diagnostic-output-checkpointer.md", "With SqliteCheckpointer")
    return
  }

  console.log("=== Streaming agent WITH CHECKPOINTER ===\n")
  const threadId2 = "diag-ckpt-" + Date.now()
  const streamStart2 = performance.now()

  try {
    const stream = await agent2.stream(
      { messages: [new HumanMessage("Please explore this codebase. Deploy 2 explore agents in parallel.")] },
      {
        configurable: { thread_id: threadId2 },
        streamMode: "messages",
      },
    )

    let eventIndex = 0
    for await (const event of stream) {
      eventIndex++
      const [msg] = Array.isArray(event) ? event : [event]

      if (msg instanceof AIMessageChunk) {
        const content = typeof msg.content === "string" ? msg.content : ""
        if (content && content.length > 1) process.stdout.write(content)

        for (const tc of msg.tool_call_chunks ?? []) {
          if (tc.name && tc.id) {
            entry2("tool_call_chunk", { id: tc.id, name: tc.name })
            console.log(`\n  [TOOL_CALL_CHUNK] ${tc.name} (${tc.id})`)
            toolTraces2.push({ id: tc.id, name: tc.name, args: tc.args, startMs: Math.round(performance.now() - streamStart2) })
          }
        }

        for (const tc of msg.tool_calls ?? []) {
          entry2("tool_call", { id: tc.id, name: tc.name, args: tc.args })
          console.log(`\n  [TOOL_CALL] ${tc.name} (${tc.id}) args=${JSON.stringify(tc.args).slice(0, 100)}`)
        }

        if (content) entry2("text", { text: content.slice(0, 200) })
      } else if (msg instanceof ToolMessage) {
        const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)
        const toolCallId = (msg as any).tool_call_id ?? ""
        entry2("ToolMessage", { tool_call_id: toolCallId, name: msg.name, content: content.slice(0, 200) })
        console.log(`\n  [TOOL_RESULT] ${msg.name} (${toolCallId}) — ${content.slice(0, 120)}`)
        const trace = toolTraces2.find(t => t.id === toolCallId)
        if (trace) { trace.endMs = Math.round(performance.now() - streamStart2); trace.result = content.slice(0, 300) }
      }
    }

    entry2("stream_complete", { totalEvents: eventIndex })
    console.log(`\n\n=== Stream completed (with checkpointer): ${eventIndex} events ===`)
  } catch (error: any) {
    crashed2 = true
    crashError2 = error
    entry2("stream_crash", { message: error.message, name: error.name, stack: error.stack })
    console.error("\n\n=== STREAM CRASHED (with checkpointer) ===")
    console.error("Error:", error.message)
    console.error("Stack:", error.stack)
  }

  await writeReport(log2, toolTraces2, crashed2, crashError2, "subagent-diagnostic-output-checkpointer.md", "With SqliteCheckpointer")

  try { await fs.rm(tmpBase2, { recursive: true, force: true }) } catch {}

  if (crashed2) {
    console.error("\n[RESULT] CHECKPOINTER TEST: CRASHED")
  } else {
    const taskCalls = toolTraces2.filter(t => t.name === "task")
    console.log(`\n[RESULT] CHECKPOINTER TEST: SUCCESS`)
    console.log(`  Task calls: ${taskCalls.length}, Completed: ${taskCalls.filter(t => t.endMs != null).length}, Orphaned: ${taskCalls.filter(t => t.endMs == null).length}`)
  }
}

// ---------------------------------------------------------------------------
// Run with checkpointer variants
// ---------------------------------------------------------------------------

// Test 1: No checkpointer (baseline)
console.log("\n╔══════════════════════════════════════════════════╗")
console.log("║  TEST 1: No Checkpointer (baseline)             ║")
console.log("╚══════════════════════════════════════════════════╝\n")
const test1Crashed = await runDiagnostic()

// Test 2: With MemorySaver checkpointer
console.log("\n╔══════════════════════════════════════════════════╗")
console.log("║  TEST 2: With SqliteCheckpointer + Tools  ║")
console.log("╚══════════════════════════════════════════════════╝\n")
await runDiagnosticWithCheckpointer()

console.log("\n\n════════════════════════════════════════════════════")
console.log("  ALL TESTS COMPLETE")
console.log("════════════════════════════════════════════════════")
process.exit(test1Crashed ? 1 : 0)
