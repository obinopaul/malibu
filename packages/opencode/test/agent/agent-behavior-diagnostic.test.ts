/**
 * Agent Behavior Diagnostic Test
 *
 * Creates a REAL agent with REAL tools, scripts specific tool call scenarios,
 * and captures EVERYTHING (reasoning, messages, tool calls, tool inputs,
 * tool messages, errors) to a detailed text file for manual inspection.
 *
 * Scenarios tested:
 *  1. Normal tool calls with valid args (glob, grep, read, bash)
 *  2. Tool calls with EMPTY or MISSING args (the crash scenario)
 *  3. Parallel tool calls (multiple tools at once)
 *  4. Task/subagent tool call (parallel subagent dispatch)
 *  5. Mixed: valid + invalid + parallel all together
 *
 * Run:
 *   cd packages/opencode
 *   bun test test/agent/agent-behavior-diagnostic.test.ts --timeout 120000
 *
 * Output:
 *   test/agent/output/agent-behavior-trace.md
 */
import { describe, test, afterAll, afterEach } from "bun:test"
import fs from "fs/promises"
import path from "path"
import { AIMessage, AIMessageChunk, HumanMessage, ToolMessage, BaseMessage } from "@langchain/core/messages"
import { ChatGenerationChunk, type ChatResult } from "@langchain/core/outputs"
import { BaseChatModel, type BaseChatModelParams } from "@langchain/core/language_models/chat_models"
import type { CallbackManagerForLLMRun } from "@langchain/core/callbacks/manager"
import { LocalShellBackend } from "deepagents"
import type { SubAgent } from "deepagents"
import { createMalibuAgent } from "../../src/agent/create-agent"
import { tmpdir } from "../fixture/fixture"
import { Instance } from "../../src/project/instance"

// ---------------------------------------------------------------------------
// Scripted Chat Model
// ---------------------------------------------------------------------------

/**
 * Fake model that cycles through pre-defined AIMessage responses.
 * Each response can include tool_calls to trigger real tool execution.
 * bindTools() shares the counter so subagent copies stay in sync.
 */
class ScriptedModel extends BaseChatModel {
  private responses: AIMessage[]
  private counter: { value: number }
  private name_: string

  constructor(
    responses: AIMessage[],
    name: string = "scripted",
    params?: BaseChatModelParams,
    counter?: { value: number },
  ) {
    super(params ?? {})
    this.responses = responses
    this.counter = counter ?? { value: 0 }
    this.name_ = name
  }

  _llmType() { return "scripted-" + this.name_ }
  _combineLLMOutput() { return [] }

  bindTools(tools: any[]): any {
    return new ScriptedModel(this.responses, this.name_, {}, this.counter)
  }

  async _generate(
    _messages: BaseMessage[],
    _options?: this["ParsedCallOptions"],
    _runManager?: CallbackManagerForLLMRun,
  ): Promise<ChatResult> {
    const idx = this.counter.value % this.responses.length
    const msg = this.responses[idx]
    this.counter.value++
    return {
      generations: [{ message: msg, text: typeof msg.content === "string" ? msg.content : "" }],
    }
  }

  async *_streamResponseChunks(
    _messages: BaseMessage[],
    _options: this["ParsedCallOptions"],
    _runManager?: CallbackManagerForLLMRun,
  ): AsyncGenerator<ChatGenerationChunk> {
    const idx = this.counter.value % this.responses.length
    const msg = this.responses[idx]
    this.counter.value++

    if (msg.tool_calls && msg.tool_calls.length > 0) {
      const chunk = new AIMessageChunk({
        content: typeof msg.content === "string" ? msg.content : "",
        tool_calls: msg.tool_calls,
      })
      yield new ChatGenerationChunk({ message: chunk, text: "" })
      return
    }

    const text = typeof msg.content === "string" ? msg.content : ""
    if (text) {
      yield new ChatGenerationChunk({
        message: new AIMessageChunk({ content: text }),
        text,
      })
    }
  }
}

// ---------------------------------------------------------------------------
// Trace Collector — captures every event to build the output file
// ---------------------------------------------------------------------------

interface TraceEvent {
  timestamp: number
  elapsed: number
  category: "REASONING" | "MESSAGE" | "TOOL_CALL" | "TOOL_INPUT" | "TOOL_MESSAGE" | "ERROR" | "INFO"
  data: Record<string, any>
}

class TraceCollector {
  private events: TraceEvent[] = []
  private startTime: number
  public scenarioName: string = ""

  constructor() {
    this.startTime = performance.now()
  }

  reset(scenarioName: string) {
    this.scenarioName = scenarioName
    this.startTime = performance.now()
  }

  add(category: TraceEvent["category"], data: Record<string, any>) {
    this.events.push({
      timestamp: Date.now(),
      elapsed: Math.round(performance.now() - this.startTime),
      category,
      data,
    })
  }

  getEvents() { return this.events }

  formatMarkdown(): string {
    const lines: string[] = []

    let currentScenario = ""
    for (const evt of this.events) {
      if (evt.data._scenario && evt.data._scenario !== currentScenario) {
        currentScenario = evt.data._scenario
        lines.push("")
        lines.push(`## Scenario: ${currentScenario}`)
        lines.push("")
      }

      const t = `[T+${String(evt.elapsed).padStart(5)}ms]`
      const cat = `[${evt.category}]`.padEnd(16)

      switch (evt.category) {
        case "REASONING":
          lines.push(`${t} ${cat} **Reasoning/Thinking:**`)
          lines.push(`    ${evt.data.text?.slice(0, 500) ?? "(empty)"}`)
          lines.push("")
          break

        case "MESSAGE":
          lines.push(`${t} ${cat} **Agent Message** (type: ${evt.data.type}):`)
          if (evt.data.content) {
            lines.push(`    ${evt.data.content.slice(0, 500)}`)
          }
          if (evt.data.tool_calls_count > 0) {
            lines.push(`    → Contains ${evt.data.tool_calls_count} tool call(s)`)
          }
          lines.push("")
          break

        case "TOOL_CALL":
          lines.push(`${t} ${cat} **Tool Call:** \`${evt.data.name}\` (id: ${evt.data.id})`)
          lines.push(`    Has args: ${evt.data.has_args ? "YES" : "**NO — EMPTY ARGS**"}`)
          if (evt.data.args_empty_keys) {
            lines.push(`    Empty/missing required keys: ${evt.data.args_empty_keys}`)
          }
          lines.push("")
          break

        case "TOOL_INPUT":
          lines.push(`${t} ${cat} **Tool Input** for \`${evt.data.name}\` (id: ${evt.data.id}):`)
          lines.push("    ```json")
          lines.push(`    ${JSON.stringify(evt.data.args, null, 2).replace(/\n/g, "\n    ")}`)
          lines.push("    ```")
          if (evt.data.args_valid === false) {
            lines.push(`    ⚠️ **INVALID INPUT** — ${evt.data.validation_issue}`)
          }
          lines.push("")
          break

        case "TOOL_MESSAGE":
          lines.push(`${t} ${cat} **Tool Result** for \`${evt.data.name}\` (call_id: ${evt.data.tool_call_id}):`)
          const content = evt.data.content ?? ""
          const isError = content.startsWith("Error:") || content.includes("error") || content.includes("Error")
          if (isError) {
            lines.push(`    ❌ **ERROR RESPONSE:**`)
          } else {
            lines.push(`    ✅ **Success:**`)
          }
          lines.push(`    ${content.slice(0, 800)}`)
          lines.push("")
          break

        case "ERROR":
          lines.push(`${t} ${cat} ❌ **ERROR:**`)
          lines.push(`    Name: ${evt.data.name}`)
          lines.push(`    Message: ${evt.data.message}`)
          if (evt.data.stack) {
            lines.push(`    Stack:`)
            lines.push(`    ${evt.data.stack.split("\n").slice(0, 8).join("\n    ")}`)
          }
          lines.push("")
          break

        case "INFO":
          lines.push(`${t} ${cat} ${evt.data.message}`)
          lines.push("")
          break
      }
    }

    return lines.join("\n")
  }
}

// Global trace collector
const trace = new TraceCollector()

// ---------------------------------------------------------------------------
// Stream processor — captures all events from agent.stream()
// ---------------------------------------------------------------------------

async function streamAndTrace(
  agent: ReturnType<typeof createMalibuAgent>,
  prompt: string,
  threadId: string,
  scenarioName: string,
) {
  trace.reset(scenarioName)
  trace.add("INFO", { _scenario: scenarioName, message: `--- Starting scenario: ${scenarioName} ---` })
  trace.add("INFO", { _scenario: scenarioName, message: `Prompt: "${prompt}"` })
  trace.add("INFO", { _scenario: scenarioName, message: `Thread: ${threadId}` })

  try {
    const stream = await agent.stream(
      { messages: [new HumanMessage(prompt)] },
      {
        configurable: { thread_id: threadId },
        streamMode: "messages",
      },
    )

    let eventCount = 0

    for await (const event of stream) {
      eventCount++
      const [msg, metadata] = Array.isArray(event) ? event : [event, undefined]

      if (msg instanceof AIMessageChunk) {
        const content = typeof msg.content === "string" ? msg.content : ""
        const contentArr = Array.isArray(msg.content) ? msg.content : []
        const tcChunks = msg.tool_call_chunks ?? []
        const tcs = msg.tool_calls ?? []

        // Text content
        if (content && content.trim()) {
          trace.add("MESSAGE", {
            _scenario: scenarioName,
            type: "AIMessageChunk",
            content,
            tool_calls_count: tcs.length,
          })
        }

        // Array content (thinking, text blocks)
        for (const part of contentArr) {
          const p = part as any
          if (p.type === "thinking" && p.thinking) {
            trace.add("REASONING", { _scenario: scenarioName, text: p.thinking })
          } else if (p.type === "reasoning" && p.reasoning) {
            trace.add("REASONING", { _scenario: scenarioName, text: p.reasoning })
          } else if (p.type === "text" && p.text && p.text.trim()) {
            trace.add("MESSAGE", {
              _scenario: scenarioName,
              type: "AIMessageChunk:text_block",
              content: p.text,
              tool_calls_count: 0,
            })
          }
        }

        // Tool call chunks (streaming partial)
        for (const tc of tcChunks) {
          if (tc.name) {
            const args = tc.args ? JSON.parse(tc.args || "{}") : {}
            const hasArgs = Object.keys(args).length > 0
            const emptyKeys = Object.entries(args)
              .filter(([_, v]) => v === "" || v === null || v === undefined)
              .map(([k]) => k)

            trace.add("TOOL_CALL", {
              _scenario: scenarioName,
              name: tc.name,
              id: tc.id ?? "?",
              has_args: hasArgs,
              args_empty_keys: emptyKeys.length > 0 ? emptyKeys.join(", ") : undefined,
            })

            trace.add("TOOL_INPUT", {
              _scenario: scenarioName,
              name: tc.name,
              id: tc.id ?? "?",
              args,
              args_valid: hasArgs && emptyKeys.length === 0,
              validation_issue: !hasArgs
                ? "No arguments provided"
                : emptyKeys.length > 0
                  ? `Empty values for: ${emptyKeys.join(", ")}`
                  : undefined,
            })
          }
        }

        // Complete tool calls
        for (const tc of tcs) {
          const args = tc.args ?? {}
          const hasArgs = Object.keys(args).length > 0
          const emptyKeys = Object.entries(args)
            .filter(([_, v]) => v === "" || v === null || v === undefined)
            .map(([k]) => k)

          trace.add("TOOL_CALL", {
            _scenario: scenarioName,
            name: tc.name,
            id: tc.id ?? "?",
            has_args: hasArgs,
            args_empty_keys: emptyKeys.length > 0 ? emptyKeys.join(", ") : undefined,
          })

          trace.add("TOOL_INPUT", {
            _scenario: scenarioName,
            name: tc.name,
            id: tc.id ?? "?",
            args,
            args_valid: hasArgs && emptyKeys.length === 0,
            validation_issue: !hasArgs
              ? "No arguments provided"
              : emptyKeys.length > 0
                ? `Empty values for: ${emptyKeys.join(", ")}`
                : undefined,
          })
        }

        // Usage metadata
        const usage = (msg as any).usage_metadata
        if (usage) {
          trace.add("INFO", {
            _scenario: scenarioName,
            message: `Token usage — input: ${usage.input_tokens}, output: ${usage.output_tokens}`,
          })
        }

      } else if (msg instanceof ToolMessage) {
        const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)
        const toolCallId = (msg as any).tool_call_id ?? "?"

        trace.add("TOOL_MESSAGE", {
          _scenario: scenarioName,
          name: msg.name ?? "unknown",
          tool_call_id: toolCallId,
          content,
        })

      } else if (msg instanceof AIMessage) {
        const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content)
        const tcs = msg.tool_calls ?? []

        trace.add("MESSAGE", {
          _scenario: scenarioName,
          type: "AIMessage (complete)",
          content,
          tool_calls_count: tcs.length,
        })

        for (const tc of tcs) {
          trace.add("TOOL_CALL", {
            _scenario: scenarioName,
            name: tc.name,
            id: tc.id ?? "?",
            has_args: Object.keys(tc.args ?? {}).length > 0,
          })
          trace.add("TOOL_INPUT", {
            _scenario: scenarioName,
            name: tc.name,
            id: tc.id ?? "?",
            args: tc.args,
          })
        }

      } else {
        trace.add("INFO", {
          _scenario: scenarioName,
          message: `Other message type: ${msg?.constructor?.name ?? typeof msg}`,
        })
      }
    }

    trace.add("INFO", {
      _scenario: scenarioName,
      message: `--- Stream completed: ${eventCount} events ---`,
    })

    return { eventCount, crashed: false }
  } catch (error: any) {
    trace.add("ERROR", {
      _scenario: scenarioName,
      name: error.name,
      message: error.message,
      stack: error.stack,
    })

    trace.add("INFO", {
      _scenario: scenarioName,
      message: `--- Stream CRASHED ---`,
    })

    return { eventCount: 0, crashed: true, error }
  }
}

// ---------------------------------------------------------------------------
// Write output file at the end
// ---------------------------------------------------------------------------

afterEach(async () => {
  await Instance.disposeAll()
})

afterAll(async () => {
  const outputPath = path.join(import.meta.dir, "output", "agent-behavior-trace.md")
  await fs.mkdir(path.dirname(outputPath), { recursive: true })

  const header = [
    "# Agent Behavior Diagnostic Trace",
    `Generated: ${new Date().toISOString()}`,
    "",
    "This file captures the COMPLETE agent execution trace for each scenario.",
    "Every tool call, tool input, tool message, reasoning block, and error is logged.",
    "",
    "**Legend:**",
    "- `[REASONING]` — Agent's thinking/reasoning content",
    "- `[MESSAGE]` — Agent's text messages",
    "- `[TOOL_CALL]` — Tool being invoked (name + ID + whether args are present)",
    "- `[TOOL_INPUT]` — Full tool input parameters (JSON)",
    "- `[TOOL_MESSAGE]` — Tool execution result returned to agent",
    "- `[ERROR]` — Errors/crashes with stack traces",
    "- `[INFO]` — Status updates",
    "",
    "---",
    "",
  ].join("\n")

  const body = trace.formatMarkdown()
  await fs.writeFile(outputPath, header + body, "utf-8")
  console.log(`\nFull trace written to: ${outputPath}`)
})

// ===========================================================================
// Test Scenarios
// ===========================================================================

describe("Agent Behavior Diagnostic", () => {

  // -------------------------------------------------------------------------
  // Scenario 1: Normal tool calls with valid args
  // -------------------------------------------------------------------------

  test("Scenario 1: Normal tool calls — glob, read, bash", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        // Create some files to find
        await fs.writeFile(path.join(tmp.path, "hello.ts"), "export const hello = 'world'\n")
        await fs.writeFile(path.join(tmp.path, "test.txt"), "This is a test file.\nLine 2.\n")

        const model = new ScriptedModel([
          // Step 1: Call glob to find files
          new AIMessage({
            content: "Let me explore the files in this directory.",
            tool_calls: [
              { id: "call_glob_1", name: "glob", args: { pattern: "**/*" } },
            ],
          }),
          // Step 2: Read a file
          new AIMessage({
            content: "Now let me read the hello.ts file.",
            tool_calls: [
              { id: "call_read_1", name: "read", args: { filePath: "hello.ts" } },
            ],
          }),
          // Step 3: Run a bash command
          new AIMessage({
            content: "Let me check the git status.",
            tool_calls: [
              { id: "call_bash_1", name: "bash", args: { command: "ls -la", description: "List directory" } },
            ],
          }),
          // Step 4: Final response
          new AIMessage({
            content: "I found 2 files in the directory. hello.ts exports a constant and test.txt has 2 lines. The git repo is initialized.",
          }),
        ])

        const backend = new LocalShellBackend({ rootDir: tmp.path })

        // Get real tools
        const { ToolRegistry } = await import("../../src/tool/registry")
        const tools = await ToolRegistry.all()

        // Convert to LangChain tools
        const { toLangChainTools } = await import("../../src/tool/langchain-adapter")
        const lcTools = await toLangChainTools(
          tools.filter((t) => ["glob", "read", "bash"].includes(t.id)),
          {
            sessionID: "diag-session" as any,
            messageID: "diag-msg" as any,
            agent: "build",
            abort: new AbortController().signal,
            messages: [],
          },
        )

        const agent = createMalibuAgent({
          model,
          tools: lcTools,
          systemPrompt: "You are a helpful assistant. Explore files using the available tools.",
          checkpointer: false,
          backend,
          subagents: [],
          name: "diag-normal",
          isAnthropicModel: false,
        })

        const result = await streamAndTrace(
          agent,
          "Explore this directory and tell me what files are here.",
          "diag-normal-" + Date.now(),
          "1. Normal tool calls (glob → read → bash)",
        )

        console.log(`  Scenario 1: ${result.eventCount} events, crashed=${result.crashed}`)
      },
    })
  }, 30_000)

  // -------------------------------------------------------------------------
  // Scenario 2: Tool calls with EMPTY/MISSING args
  // -------------------------------------------------------------------------

  test("Scenario 2: Tool calls with empty args — triggers validation errors", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const model = new ScriptedModel([
          // Step 1: Call read with NO file_path (EMPTY ARGS)
          new AIMessage({
            content: "Let me read a file.",
            tool_calls: [
              { id: "call_read_empty", name: "read", args: {} },
            ],
          }),
          // Step 2: Call bash with empty command
          new AIMessage({
            content: "Let me run a command.",
            tool_calls: [
              { id: "call_bash_empty", name: "bash", args: { command: "" } },
            ],
          }),
          // Step 3: Call glob with empty pattern
          new AIMessage({
            content: "Let me search for files.",
            tool_calls: [
              { id: "call_glob_empty", name: "glob", args: { pattern: "" } },
            ],
          }),
          // Step 4: Call grep with empty pattern
          new AIMessage({
            content: "Let me search code.",
            tool_calls: [
              { id: "call_grep_empty", name: "grep", args: {} },
            ],
          }),
          // Step 5: Final response (if agent gets here)
          new AIMessage({
            content: "All my tool calls had errors because I provided empty arguments. I should provide valid inputs.",
          }),
        ])

        const backend = new LocalShellBackend({ rootDir: tmp.path })

        const { ToolRegistry } = await import("../../src/tool/registry")
        const tools = await ToolRegistry.all()

        const { toLangChainTools } = await import("../../src/tool/langchain-adapter")
        const lcTools = await toLangChainTools(
          tools.filter((t) => ["glob", "read", "bash", "grep"].includes(t.id)),
          {
            sessionID: "diag-session" as any,
            messageID: "diag-msg" as any,
            agent: "build",
            abort: new AbortController().signal,
            messages: [],
          },
        )

        const agent = createMalibuAgent({
          model,
          tools: lcTools,
          systemPrompt: "You are a helpful assistant.",
          checkpointer: false,
          backend,
          subagents: [],
          name: "diag-empty-args",
          isAnthropicModel: false,
        })

        const result = await streamAndTrace(
          agent,
          "Try to use tools.",
          "diag-empty-" + Date.now(),
          "2. Empty/missing args — validation error handling",
        )

        console.log(`  Scenario 2: ${result.eventCount} events, crashed=${result.crashed}`)
        if (result.crashed) {
          console.error(`  >>> SYSTEM CRASHED on empty args: ${result.error?.message}`)
        }
      },
    })
  }, 30_000)

  // -------------------------------------------------------------------------
  // Scenario 3: Parallel tool calls
  // -------------------------------------------------------------------------

  test("Scenario 3: Parallel tool calls — 3 tools at once", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        await fs.writeFile(path.join(tmp.path, "src.ts"), "export function main() { return 42 }\n")
        await fs.writeFile(path.join(tmp.path, "readme.md"), "# Project\nThis is a test project.\n")

        const model = new ScriptedModel([
          // Step 1: THREE parallel tool calls
          new AIMessage({
            content: "I'll explore the codebase using multiple tools simultaneously.",
            tool_calls: [
              { id: "call_par_glob", name: "glob", args: { pattern: "**/*" } },
              { id: "call_par_bash", name: "bash", args: { command: "git log --oneline -5", description: "Show recent commits" } },
              { id: "call_par_read", name: "read", args: { filePath: "src.ts" } },
            ],
          }),
          // Step 2: TWO more parallel calls
          new AIMessage({
            content: "Let me also check the readme.",
            tool_calls: [
              { id: "call_par2_read", name: "read", args: { filePath: "readme.md" } },
              { id: "call_par2_bash", name: "bash", args: { command: "wc -l *.ts *.md 2>/dev/null || echo 'no files'", description: "Count lines" } },
            ],
          }),
          // Step 3: Final
          new AIMessage({
            content: "The codebase has 2 files: src.ts with a main function and readme.md with project description.",
          }),
        ])

        const backend = new LocalShellBackend({ rootDir: tmp.path })

        const { ToolRegistry } = await import("../../src/tool/registry")
        const tools = await ToolRegistry.all()

        const { toLangChainTools } = await import("../../src/tool/langchain-adapter")
        const lcTools = await toLangChainTools(
          tools.filter((t) => ["glob", "read", "bash", "grep"].includes(t.id)),
          {
            sessionID: "diag-session" as any,
            messageID: "diag-msg" as any,
            agent: "build",
            abort: new AbortController().signal,
            messages: [],
          },
        )

        const agent = createMalibuAgent({
          model,
          tools: lcTools,
          systemPrompt: "You are a helpful assistant. Use tools to explore.",
          checkpointer: false,
          backend,
          subagents: [],
          name: "diag-parallel",
          isAnthropicModel: false,
        })

        const result = await streamAndTrace(
          agent,
          "Explore this codebase thoroughly.",
          "diag-parallel-" + Date.now(),
          "3. Parallel tool calls (3 tools, then 2 tools)",
        )

        console.log(`  Scenario 3: ${result.eventCount} events, crashed=${result.crashed}`)
      },
    })
  }, 30_000)

  // -------------------------------------------------------------------------
  // Scenario 4: Parallel subagent dispatch via task tool
  // -------------------------------------------------------------------------

  test("Scenario 4: Parallel subagent dispatch via task tool", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        await fs.writeFile(path.join(tmp.path, "app.ts"), "console.log('hello')\n")

        const subagentModel = new ScriptedModel([
          new AIMessage({ content: "Subagent finished exploring. Found the app.ts file with a console.log statement." }),
        ], "subagent")

        const parentModel = new ScriptedModel([
          // Step 1: Dispatch 2 subagents in parallel
          new AIMessage({
            content: "I'll dispatch two agents to explore different aspects.",
            tool_calls: [
              {
                id: "call_task_1",
                name: "task",
                args: { description: "Explore the TypeScript files", subagent_type: "explore" },
              },
              {
                id: "call_task_2",
                name: "task",
                args: { description: "Search for console.log patterns", subagent_type: "explore" },
              },
            ],
          }),
          // Step 2: Summary
          new AIMessage({
            content: "Both explorations are complete. The codebase has a single TypeScript file.",
          }),
        ], "parent")

        const explore: SubAgent = {
          name: "explore",
          description: "Fast agent for exploring codebases",
          systemPrompt: "You are an explore agent. Return findings immediately.",
          model: subagentModel,
          tools: [],
        }

        const backend = new LocalShellBackend({ rootDir: tmp.path })

        const agent = createMalibuAgent({
          model: parentModel,
          tools: [],
          systemPrompt: "You are a helpful assistant. Use the task tool to delegate work to subagents.",
          checkpointer: false,
          backend,
          subagents: [explore],
          name: "diag-subagent",
          isAnthropicModel: false,
        })

        const result = await streamAndTrace(
          agent,
          "Explore this codebase using 2 parallel subagents.",
          "diag-subagent-" + Date.now(),
          "4. Parallel subagent dispatch (2 task tool calls)",
        )

        console.log(`  Scenario 4: ${result.eventCount} events, crashed=${result.crashed}`)
      },
    })
  }, 60_000)

  // -------------------------------------------------------------------------
  // Scenario 5: Mixed — valid, invalid, and parallel all at once
  // -------------------------------------------------------------------------

  test("Scenario 5: Mixed — valid + empty args + parallel", async () => {
    await using tmp = await tmpdir({ git: true })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        await fs.writeFile(path.join(tmp.path, "index.ts"), "export default 42\n")

        const model = new ScriptedModel([
          // Step 1: Mix of valid and invalid parallel calls
          new AIMessage({
            content: "Let me try several tools at once.",
            tool_calls: [
              // Valid: glob
              { id: "call_mix_glob", name: "glob", args: { pattern: "**/*.ts" } },
              // INVALID: read with empty args
              { id: "call_mix_read_empty", name: "read", args: {} },
              // Valid: bash
              { id: "call_mix_bash", name: "bash", args: { command: "echo hello", description: "Echo test" } },
            ],
          }),
          // Step 2: Another round — one valid, one with empty command
          new AIMessage({
            content: "Let me try again with some corrections.",
            tool_calls: [
              // Valid: read with proper path
              { id: "call_mix_read_ok", name: "read", args: { filePath: "index.ts" } },
              // INVALID: bash with empty command
              { id: "call_mix_bash_empty", name: "bash", args: { command: "", description: "" } },
            ],
          }),
          // Step 3: Final
          new AIMessage({
            content: "Some calls succeeded and some failed due to empty arguments. The valid calls returned useful results.",
          }),
        ])

        const backend = new LocalShellBackend({ rootDir: tmp.path })

        const { ToolRegistry } = await import("../../src/tool/registry")
        const tools = await ToolRegistry.all()

        const { toLangChainTools } = await import("../../src/tool/langchain-adapter")
        const lcTools = await toLangChainTools(
          tools.filter((t) => ["glob", "read", "bash", "grep"].includes(t.id)),
          {
            sessionID: "diag-session" as any,
            messageID: "diag-msg" as any,
            agent: "build",
            abort: new AbortController().signal,
            messages: [],
          },
        )

        const agent = createMalibuAgent({
          model,
          tools: lcTools,
          systemPrompt: "You are a helpful assistant.",
          checkpointer: false,
          backend,
          subagents: [],
          name: "diag-mixed",
          isAnthropicModel: false,
        })

        const result = await streamAndTrace(
          agent,
          "Try using multiple tools, some may fail.",
          "diag-mixed-" + Date.now(),
          "5. Mixed: valid + empty args + parallel (3 calls, then 2 calls)",
        )

        console.log(`  Scenario 5: ${result.eventCount} events, crashed=${result.crashed}`)
        if (result.crashed) {
          console.error(`  >>> SYSTEM CRASHED on mixed scenario: ${result.error?.message}`)
          console.error(`  This shows the agent cannot recover from validation errors in parallel calls`)
        }
      },
    })
  }, 30_000)
})
