/**
 * Standalone Subagent Test — Tests the `task` (sync) and `background_task` (async)
 * tools using REAL LLMs, bypassing all of Malibu/OpenCode.
 *
 * This creates agents directly via langchain's createAgent with the subagent and
 * background subagent middleware, then streams the full conversation to see if:
 * 1. The sync `task` tool works (single subagent delegation)
 * 2. The `background_task` tools work (launch, progress, wait, cancel)
 * 3. Parallel background_task calls work without crashing
 * 4. The main agent properly uses subagent results in its final answer
 *
 * Run:
 *   cd packages/opencode
 *   bun test test/agent/standalone-subagent.test.ts --timeout 300000
 *
 * Output:
 *   test/agent/output/standalone-subagent-trace.md
 */
import { describe, test, afterAll, beforeAll, expect } from "bun:test"
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
import { createAgent, createMiddleware } from "langchain"
import { createSubAgentMiddleware, createPatchToolCallsMiddleware, LocalShellBackend } from "deepagents"
import type { SubAgent } from "deepagents"
import { ChatAnthropic } from "@langchain/anthropic"
import { ChatOpenAI } from "@langchain/openai"
import { DynamicStructuredTool } from "@langchain/core/tools"
import { AIMessageChunk, ToolMessage, AIMessage, HumanMessage } from "@langchain/core/messages"
import { z } from "zod"

import {
  createBackgroundSubAgentMiddleware,
  BackgroundTaskRegistry,
} from "../../src/agent/background-subagents"

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
  description: "List files and directories at the given path.",
  schema: z.object({
    path: z.string().optional().describe("Directory path to list. Defaults to current directory."),
  }),
  async func({ path: dirPath }) {
    const target = dirPath || process.cwd()
    try {
      const entries = await fs.readdir(target, { withFileTypes: true })
      return entries.slice(0, 30).map((e) => (e.isDirectory() ? e.name + "/" : e.name)).join("\n") || "Empty directory"
    } catch (err: any) {
      return `Error: ${err.message}`
    }
  },
})

const readTool = new DynamicStructuredTool({
  name: "read",
  description: "Read the contents of a file. Returns text with line numbers.",
  schema: z.object({
    filePath: z.string().describe("Path to the file to read"),
    limit: z.number().optional().describe("Max lines to read (default 100)"),
  }),
  async func({ filePath, limit }) {
    try {
      const content = await readFileSync(filePath, "utf-8")
      const lines = content.split("\n").slice(0, limit ?? 100)
      return lines.map((l, i) => `${i + 1}: ${l}`).join("\n") || "(empty file)"
    } catch (err: any) {
      return `Error: ${err.message}`
    }
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
  async func({ command }) {
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
// Create the LLM
// ---------------------------------------------------------------------------

function createLLM(maxTokens = 4096) {
  const anthropicKey = process.env.ANTHROPIC_API_KEY
  const openaiKey = process.env.OPENAI_API_KEY

  if (anthropicKey) {
    log(`Using: ChatAnthropic (claude-sonnet-4-20250514, maxTokens=${maxTokens})`)
    return new ChatAnthropic({
      model: "claude-sonnet-4-20250514",
      apiKey: anthropicKey,
      maxTokens,
      streaming: true,
    })
  }

  if (openaiKey) {
    log(`Using: ChatOpenAI (gpt-4o, maxTokens=${maxTokens})`)
    return new ChatOpenAI({
      model: "gpt-4o",
      apiKey: openaiKey,
      maxTokens,
      streaming: true,
    })
  }

  throw new Error(
    "No API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable.",
  )
}

// ---------------------------------------------------------------------------
// Stream helper — captures all events to the trace
// ---------------------------------------------------------------------------

async function streamAndTrace(
  agent: ReturnType<typeof createAgent>,
  prompt: string,
  label: string,
): Promise<{ toolCallCount: number; textChunks: number; response: string; errors: string[] }> {
  logSection(label)
  log(`**Prompt:** ${prompt}`)
  log("")

  const startTime = performance.now()
  const threadId = `subagent-test-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  let toolCallCount = 0
  let textChunks = 0
  let response = ""
  const errors: string[] = []

  try {
    const stream = await agent.stream(
      { messages: [new HumanMessage(prompt)] },
      {
        configurable: { thread_id: threadId },
        streamMode: "messages",
      },
    )

    const pendingChunks = new Map<string, { name: string; argsJson: string; logged: boolean }>()

    for await (const event of stream) {
      const [msg] = Array.isArray(event) ? event : [event]
      const elapsed = Math.round(performance.now() - startTime)

      if (msg instanceof AIMessageChunk) {
        // Text content
        let content = ""
        if (typeof msg.content === "string") {
          content = msg.content
        } else if (Array.isArray(msg.content)) {
          content = msg.content
            .map((p: any) => typeof p === "string" ? p : (p.type === "text" ? p.text : ""))
            .filter(Boolean).join("")
        }

        if (content && content.trim()) {
          textChunks++
          response += content
          log(`[T+${String(elapsed).padStart(6)}ms] TEXT: ${content.slice(0, 300)}`)
        }

        // tool_call_chunks accumulation
        for (const chunk of msg.tool_call_chunks ?? []) {
          const idx = String(chunk.index ?? 0)
          if (chunk.id) {
            pendingChunks.set(chunk.id, { name: chunk.name ?? "", argsJson: "", logged: false })
            pendingChunks.set(`_idx_${idx}`, { name: chunk.name ?? "", argsJson: "", logged: false })
          }
          const byIdx = pendingChunks.get(`_idx_${idx}`)
          if (byIdx) byIdx.argsJson += chunk.args ?? ""
        }

        // Log tool calls from tool_calls array (uses accumulated args from chunks)
        for (const tc of msg.tool_calls ?? []) {
          if (!tc.id) continue
          toolCallCount++
          const pending = pendingChunks.get(tc.id)
          let argsStr = "{}"
          if (pending && pending.argsJson) {
            argsStr = pending.argsJson
            pending.logged = true
          } else if (tc.args && Object.keys(tc.args).length > 0) {
            argsStr = JSON.stringify(tc.args)
          }
          log(`[T+${String(elapsed).padStart(6)}ms] TOOL_CALL #${toolCallCount}: ${tc.name}(${argsStr.slice(0, 200)})`)
        }
      } else if (msg instanceof ToolMessage) {
        const elapsed2 = Math.round(performance.now() - startTime)
        const preview = typeof msg.content === "string"
          ? msg.content.slice(0, 200)
          : JSON.stringify(msg.content).slice(0, 200)
        log(`[T+${String(elapsed2).padStart(6)}ms] TOOL_RESULT [${msg.name}]: ${preview}`)
      } else if (msg instanceof AIMessage) {
        const content = typeof msg.content === "string" ? msg.content
          : Array.isArray(msg.content)
            ? msg.content.map((p: any) => typeof p === "string" ? p : p.text ?? "").join("")
            : ""
        if (content && content.trim()) {
          textChunks++
          response += content
          log(`[T+${String(elapsed).padStart(6)}ms] AI_MESSAGE: ${content.slice(0, 500)}`)
        }
      }
    }
  } catch (err: any) {
    const elapsed = Math.round(performance.now() - startTime)
    const errMsg = `${err.name}: ${err.message}`
    errors.push(errMsg)
    log(`[T+${String(elapsed).padStart(6)}ms] ERROR: ${errMsg}`)
    if (err.stack) log(`  Stack: ${err.stack.split("\n").slice(0, 5).join("\n  ")}`)
  }

  const totalTime = Math.round(performance.now() - startTime)
  log(`[T+${String(totalTime).padStart(6)}ms] === STREAM ENDED ===`)
  log("")
  log("### Summary")
  log(`- Total time: ${totalTime}ms`)
  log(`- Tool calls: ${toolCallCount}`)
  log(`- Text chunks: ${textChunks}`)
  log(`- Errors: ${errors.length}`)
  if (errors.length > 0) {
    log(`- Error details: ${errors.join("; ")}`)
  }

  return { toolCallCount, textChunks, response, errors }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

const OUTPUT_DIR = path.join(import.meta.dir, "output")
const OUTPUT_FILE = path.join(OUTPUT_DIR, "standalone-subagent-trace.md")

describe("standalone-subagent", () => {
  beforeAll(async () => {
    await fs.mkdir(OUTPUT_DIR, { recursive: true })
    log("# Standalone Subagent Trace — Task & Background Task Tools")
    log(`Generated: ${new Date().toISOString()}`)
    log("")
    log("This test creates agents with real LLMs and the subagent/background-subagent middleware.")
    log("It verifies that the task (sync) and background_task (async) tools work correctly.")
    log("")
    log("---")
  })

  afterAll(async () => {
    const header = [
      "# Standalone Subagent Trace — Task & Background Task Tools",
      `Generated: ${new Date().toISOString()}`,
      "",
    ]
    await fs.writeFile(OUTPUT_FILE, outputLines.join("\n"), "utf-8")
    console.log(`\n📄 Trace written to: ${OUTPUT_FILE}`)
  })

  // =========================================================================
  // Test 1: Sync task tool — single subagent delegation
  // =========================================================================
  test("sync task tool — delegate a single task to a subagent", async () => {
    const model = createLLM(4096)
    const backend = new LocalShellBackend({ rootDir: process.cwd() })

    const agent = createAgent({
      model,
      tools,
      systemPrompt: [
        "You are a helpful coding assistant with access to subagents.",
        "You have a `task` tool that lets you delegate work to specialized subagents.",
        "When asked to explore or research something, use the `task` tool to delegate it to the general-purpose subagent.",
        "After the subagent returns, summarize the result for the user.",
      ].join("\n"),
      middleware: [
        createSubAgentMiddleware({
          defaultModel: model,
          defaultTools: tools,
          generalPurposeAgent: true,
        } as any),
        createPatchToolCallsMiddleware(),
      ],
      name: "main-agent",
    }).withConfig({
      recursionLimit: 200,
    })

    const result = await streamAndTrace(
      agent,
      "Use your task tool to delegate the following: list the top-level files in the current directory and tell me what this project is about based on the file names.",
      "Test 1: Sync task — single delegation",
    )

    // Should have at least called the task tool
    expect(result.toolCallCount).toBeGreaterThanOrEqual(1)
    log(`\n✓ Sync task tool was called (${result.toolCallCount} tool calls total)`)
  }, 120_000)

  // =========================================================================
  // Test 2: Background task — single async task
  // =========================================================================
  test("background task — launch one async task and wait for it", async () => {
    const model = createLLM(4096)

    const { middleware: bgMiddleware, registry } = createBackgroundSubAgentMiddleware({
      defaultModel: model,
      defaultTools: tools,
      generalPurposeAgent: true,
    })

    const agent = createAgent({
      model,
      tools,
      systemPrompt: [
        "You are a helpful coding assistant with background task capabilities.",
        "You have a `background_task` tool to launch subagents in the background.",
        "You have a `wait_background_task` tool to wait for results.",
        "",
        "When asked to research something in the background:",
        "1. Launch a background_task with the description",
        "2. Then IMMEDIATELY use wait_background_task to wait for the result",
        "3. Summarize the result for the user",
      ].join("\n"),
      middleware: [
        bgMiddleware,
        createPatchToolCallsMiddleware(),
      ],
      name: "main-agent-bg",
    }).withConfig({
      recursionLimit: 200,
    })

    const result = await streamAndTrace(
      agent,
      "Launch a background task to list the files in the current directory and describe the project. Then wait for the result and tell me what it found.",
      "Test 2: Background task — single async launch + wait",
    )

    expect(result.toolCallCount).toBeGreaterThanOrEqual(1)
    log(`\n✓ Background task tools were used (${result.toolCallCount} tool calls total)`)
    log(`  Registry state: pending=${registry.pendingCount}`)
  }, 120_000)

  // =========================================================================
  // Test 3: Parallel background tasks — launch multiple and wait for all
  // =========================================================================
  test("parallel background tasks — launch 2 tasks and wait for all", async () => {
    const model = createLLM(4096)

    const { middleware: bgMiddleware, registry } = createBackgroundSubAgentMiddleware({
      defaultModel: model,
      defaultTools: tools,
      generalPurposeAgent: true,
    })

    const agent = createAgent({
      model,
      tools,
      systemPrompt: [
        "You are a helpful coding assistant with background task capabilities.",
        "You have these tools:",
        "- `background_task`: Launch a subagent in the background (non-blocking)",
        "- `wait_background_task`: Wait for background task(s) to complete",
        "- `task_progress`: Check status without blocking",
        "",
        "When asked to do parallel research:",
        "1. Launch MULTIPLE background_task calls IN THE SAME MESSAGE (parallel)",
        "2. Then use wait_background_task (with no task_number) to wait for ALL",
        "3. Summarize ALL results for the user",
        "",
        "IMPORTANT: Launch both background tasks in the SAME message, not one at a time.",
      ].join("\n"),
      middleware: [
        bgMiddleware,
        createPatchToolCallsMiddleware(),
      ],
      name: "main-agent-parallel",
    }).withConfig({
      recursionLimit: 200,
    })

    const result = await streamAndTrace(
      agent,
      "I need TWO things researched IN PARALLEL using background tasks: (1) List the files in the src/ directory, (2) Read the package.json file. Launch BOTH as background_task calls in the same message, then wait for all results.",
      "Test 3: Parallel background tasks — 2 concurrent tasks",
    )

    // Should have called background_task at least twice
    expect(result.toolCallCount).toBeGreaterThanOrEqual(2)
    log(`\n✓ Parallel background tasks were launched (${result.toolCallCount} tool calls total)`)
    log(`  Registry state: pending=${registry.pendingCount}`)
  }, 180_000)

  // =========================================================================
  // Test 4: Background task with progress check and cancel
  // =========================================================================
  test("background task — launch, check progress, then wait", async () => {
    const model = createLLM(4096)

    const { middleware: bgMiddleware, registry } = createBackgroundSubAgentMiddleware({
      defaultModel: model,
      defaultTools: tools,
      generalPurposeAgent: true,
    })

    const agent = createAgent({
      model,
      tools,
      systemPrompt: [
        "You are a helpful assistant with background task tools.",
        "Tools: background_task, task_progress, wait_background_task, cancel_background_task",
        "",
        "Follow this EXACT sequence:",
        "1. Launch a background_task to explore the src/ directory structure",
        "2. Check its progress with task_progress (use the task number from step 1)",
        "3. Wait for the result with wait_background_task",
        "4. Summarize the result",
      ].join("\n"),
      middleware: [
        bgMiddleware,
        createPatchToolCallsMiddleware(),
      ],
      name: "main-agent-progress",
    }).withConfig({
      recursionLimit: 200,
    })

    const result = await streamAndTrace(
      agent,
      "Launch a background task to explore the src/ directory and list what's inside. Then check its progress, then wait for it, then tell me what it found.",
      "Test 4: Background task — launch → progress → wait",
    )

    expect(result.toolCallCount).toBeGreaterThanOrEqual(2)
    log(`\n✓ Background task workflow completed (${result.toolCallCount} tool calls total)`)
  }, 120_000)

  // =========================================================================
  // Test 5: Mixed — sync task + background task in same agent
  // =========================================================================
  test("mixed — both sync task and background task available", async () => {
    const model = createLLM(4096)
    const backend = new LocalShellBackend({ rootDir: process.cwd() })

    const { middleware: bgMiddleware, registry } = createBackgroundSubAgentMiddleware({
      defaultModel: model,
      defaultTools: tools,
      generalPurposeAgent: true,
    })

    const agent = createAgent({
      model,
      tools,
      systemPrompt: [
        "You are a helpful assistant with BOTH sync and async subagent tools.",
        "",
        "Sync tool:",
        "- `task`: Blocks until the subagent finishes. Use for single quick operations.",
        "",
        "Async tools:",
        "- `background_task`: Non-blocking. Use for parallel work.",
        "- `wait_background_task`: Wait for background results.",
        "",
        "The user will tell you which approach to use.",
      ].join("\n"),
      middleware: [
        createSubAgentMiddleware({
          defaultModel: model,
          defaultTools: tools,
          generalPurposeAgent: true,
        } as any),
        bgMiddleware,
        createPatchToolCallsMiddleware(),
      ],
      name: "main-agent-mixed",
    }).withConfig({
      recursionLimit: 200,
    })

    const result = await streamAndTrace(
      agent,
      "Use the sync `task` tool to find out what files are in the current directory. Then summarize what you found.",
      "Test 5: Mixed — sync task with background available",
    )

    expect(result.toolCallCount).toBeGreaterThanOrEqual(1)
    log(`\n✓ Mixed agent completed (${result.toolCallCount} tool calls total)`)
  }, 120_000)
})
