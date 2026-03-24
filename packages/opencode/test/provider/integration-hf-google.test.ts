/**
 * Integration tests for Hugging Face and Google Gemini providers.
 * These tests make real API calls — require HF_TOKEN and GOOGLE_API_KEY env vars.
 *
 * The test preload deletes API keys, so we read .env directly.
 * Run: bun test test/provider/integration-hf-google.test.ts --timeout 60000
 */
import { describe, test, expect } from "bun:test"
import { ChatOpenAI } from "@langchain/openai"
import { ChatGoogleGenerativeAI } from "@langchain/google-genai"
import { DynamicStructuredTool } from "@langchain/core/tools"
import { HumanMessage } from "@langchain/core/messages"
import z from "zod"
import { ProviderTransform } from "../../src/provider/transform"
import fs from "fs"
import path from "path"

// Read .env file directly since test preload clears process.env keys
function loadEnvFile(): Record<string, string> {
  const envPath = path.resolve(import.meta.dir, "../../../../.env")
  if (!fs.existsSync(envPath)) return {}
  const content = fs.readFileSync(envPath, "utf-8")
  const vars: Record<string, string> = {}
  for (const line of content.split("\n")) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith("#")) continue
    const eqIndex = trimmed.indexOf("=")
    if (eqIndex === -1) continue
    const key = trimmed.slice(0, eqIndex).trim()
    let value = trimmed.slice(eqIndex + 1).trim()
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1)
    }
    vars[key] = value
  }
  return vars
}

const envVars = loadEnvFile()
const HF_TOKEN = process.env.HF_TOKEN || envVars.HF_TOKEN
const GOOGLE_API_KEY = process.env.GOOGLE_API_KEY || envVars.GOOGLE_API_KEY

// Simple tool for testing tool calling
const weatherTool = new DynamicStructuredTool({
  name: "get_weather",
  description: "Get current weather for a location",
  schema: z.object({
    location: z.string().describe("City name"),
  }),
  func: async ({ location }) => {
    return `Weather in ${location}: 72°F, sunny`
  },
})

// Tool with nested schema
const editTool = new DynamicStructuredTool({
  name: "edit_file",
  description: "Edit a file by applying changes",
  schema: z.object({
    filePath: z.string().describe("Path to the file"),
    edits: z.array(
      z.object({
        lineNumber: z.number().describe("Line number to edit"),
        content: z.string().describe("New content for the line"),
      }),
    ).describe("List of edits to apply"),
  }),
  func: async ({ filePath, edits }) => {
    return `Applied ${edits.length} edits to ${filePath}`
  },
})

describe("Hugging Face Integration", () => {
  test("basic chat completion", async () => {
    if (!HF_TOKEN) {
      console.warn("⚠ Skipping — HF_TOKEN not set")
      return
    }

    const model = new ChatOpenAI({
      model: "meta-llama/Llama-3.3-70B-Instruct",
      apiKey: HF_TOKEN,
      configuration: {
        baseURL: "https://router.huggingface.co/v1",
      },
      temperature: 0.1,
      maxTokens: 100,
      streaming: false,
    })

    const response = await model.invoke([new HumanMessage("Say hello in exactly 3 words.")])
    console.log("HF basic response:", response.content)
    expect(response.content).toBeTruthy()
    expect(typeof response.content).toBe("string")
  }, 30000)

  test("streaming chat completion", async () => {
    if (!HF_TOKEN) {
      console.warn("⚠ Skipping — HF_TOKEN not set")
      return
    }

    const model = new ChatOpenAI({
      model: "meta-llama/Llama-3.3-70B-Instruct",
      apiKey: HF_TOKEN,
      configuration: {
        baseURL: "https://router.huggingface.co/v1",
      },
      temperature: 0.1,
      maxTokens: 100,
      streaming: true,
    })

    const chunks: string[] = []
    const stream = await model.stream([new HumanMessage("Count from 1 to 5.")])
    for await (const chunk of stream) {
      if (chunk.content) {
        chunks.push(String(chunk.content))
      }
    }
    const fullText = chunks.join("")
    console.log("HF streaming response:", fullText.substring(0, 200))
    expect(chunks.length).toBeGreaterThan(1)
    expect(fullText).toBeTruthy()
  }, 30000)

  test("tool calling", async () => {
    if (!HF_TOKEN) {
      console.warn("⚠ Skipping — HF_TOKEN not set")
      return
    }

    const model = new ChatOpenAI({
      model: "meta-llama/Llama-3.3-70B-Instruct",
      apiKey: HF_TOKEN,
      configuration: {
        baseURL: "https://router.huggingface.co/v1",
      },
      temperature: 0,
      maxTokens: 200,
    })

    const modelWithTools = model.bindTools([weatherTool])
    const response = await modelWithTools.invoke([
      new HumanMessage("What's the weather in San Francisco?"),
    ])

    console.log("HF tool call response:", JSON.stringify(response.tool_calls, null, 2))
    expect(response.tool_calls).toBeDefined()
    expect(response.tool_calls!.length).toBeGreaterThan(0)
    expect(response.tool_calls![0].name).toBe("get_weather")
    expect(response.tool_calls![0].args.location).toBeTruthy()
  }, 30000)

  test("tool calling with complex nested schema", async () => {
    if (!HF_TOKEN) {
      console.warn("⚠ Skipping — HF_TOKEN not set")
      return
    }

    const model = new ChatOpenAI({
      model: "meta-llama/Llama-3.3-70B-Instruct",
      apiKey: HF_TOKEN,
      configuration: {
        baseURL: "https://router.huggingface.co/v1",
      },
      temperature: 0,
      maxTokens: 300,
    })

    const modelWithTools = model.bindTools([editTool])
    const response = await modelWithTools.invoke([
      new HumanMessage('Edit file /tmp/test.txt: change line 1 to "hello" and line 5 to "world"'),
    ])

    console.log("HF complex tool call:", JSON.stringify(response.tool_calls, null, 2))
    expect(response.tool_calls).toBeDefined()
    expect(response.tool_calls!.length).toBeGreaterThan(0)
    expect(response.tool_calls![0].name).toBe("edit_file")
    expect(response.tool_calls![0].args.edits.length).toBe(2)
  }, 30000)
})

describe("Google Gemini Integration", () => {
  test("basic chat completion", async () => {
    if (!GOOGLE_API_KEY) {
      console.warn("⚠ Skipping — GOOGLE_API_KEY not set")
      return
    }

    const model = new ChatGoogleGenerativeAI({
      model: "gemini-2.0-flash",
      apiKey: GOOGLE_API_KEY,
      temperature: 0.1,
      maxOutputTokens: 100,
      streaming: false,
    })

    const response = await model.invoke([new HumanMessage("Say hello in exactly 3 words.")])
    console.log("Google basic response:", response.content)
    expect(response.content).toBeTruthy()
    expect(typeof response.content).toBe("string")
  }, 30000)

  test("streaming chat completion", async () => {
    if (!GOOGLE_API_KEY) {
      console.warn("⚠ Skipping — GOOGLE_API_KEY not set")
      return
    }

    const model = new ChatGoogleGenerativeAI({
      model: "gemini-2.0-flash",
      apiKey: GOOGLE_API_KEY,
      temperature: 0.1,
      maxOutputTokens: 100,
      streaming: true,
    })

    const chunks: string[] = []
    const stream = await model.stream([new HumanMessage("Count from 1 to 5.")])
    for await (const chunk of stream) {
      if (chunk.content) {
        chunks.push(String(chunk.content))
      }
    }
    const fullText = chunks.join("")
    console.log("Google streaming response:", fullText.substring(0, 200))
    expect(chunks.length).toBeGreaterThan(0)
    expect(fullText).toBeTruthy()
  }, 30000)

  test("tool calling with patched invocationParams", async () => {
    if (!GOOGLE_API_KEY) {
      console.warn("⚠ Skipping — GOOGLE_API_KEY not set")
      return
    }

    // Simulate the factory patch from langchain-factory.ts
    const chatModel = new ChatGoogleGenerativeAI({
      model: "gemini-2.0-flash",
      apiKey: GOOGLE_API_KEY,
      temperature: 0,
      maxOutputTokens: 300,
    })

    const origInvocationParams = chatModel.invocationParams.bind(chatModel)
    chatModel.invocationParams = (opts?: any) => {
      const params = origInvocationParams(opts)
      if (params.tools) {
        params.tools = params.tools.map((toolGroup: any) => {
          if (!toolGroup.functionDeclarations) return toolGroup
          return {
            ...toolGroup,
            functionDeclarations: toolGroup.functionDeclarations.map((fn: any) => {
              if (!fn.parameters) return fn
              return {
                ...fn,
                parameters: ProviderTransform.derefJsonSchema(fn.parameters),
              }
            }),
          }
        })
      }
      return params
    }

    const modelWithTools = chatModel.bindTools([weatherTool, editTool])
    const response = await modelWithTools.invoke([
      new HumanMessage("What's the weather in Paris?"),
    ])

    console.log("Google patched tool call:", JSON.stringify(response.tool_calls, null, 2))
    expect(response.tool_calls).toBeDefined()
    expect(response.tool_calls!.length).toBeGreaterThan(0)
    expect(response.tool_calls![0].name).toBe("get_weather")
  }, 30000)
})

describe("derefJsonSchema with real LangChain toJsonSchema output", () => {
  test("dereferences $ref from recursive Zod schemas via LangChain's toJsonSchema", async () => {
    const { toJsonSchema } = await import("@langchain/core/utils/json_schema")

    // Recursive/lazy schemas produce $ref in LangChain's toJsonSchema
    const treeNode: z.ZodType<any> = z.lazy(() => z.object({
      name: z.string(),
      children: z.array(treeNode).optional(),
    }))

    const schema = z.object({ root: treeNode })
    const jsonSchema = toJsonSchema(schema) as any

    console.log("Recursive schema (before deref):", JSON.stringify(jsonSchema, null, 2))

    // Verify it HAS $ref before deref
    expect(JSON.stringify(jsonSchema).includes('"$ref"')).toBe(true)

    const dereffed = ProviderTransform.derefJsonSchema(jsonSchema)
    console.log("Recursive schema (after deref):", JSON.stringify(dereffed, null, 2))

    // Verify no $ref remains
    expect(JSON.stringify(dereffed).includes('"$ref"')).toBe(false)
    expect(dereffed.$defs).toBeUndefined()

    // Verify structure is preserved
    expect(dereffed.type).toBe("object")
    expect(dereffed.properties.root.type).toBe("object")
    expect(dereffed.properties.root.properties.name.type).toBe("string")
    // Circular ref collapses to { type: "object" }
    expect(dereffed.properties.root.properties.children.items.type).toBe("object")
  })

  test("handles schema with $defs but no $ref usage", () => {
    // Some converters emit $defs even when not referenced
    const schema = {
      type: "object",
      properties: { name: { type: "string" } },
      $defs: { Unused: { type: "number" } },
    }
    const result = ProviderTransform.derefJsonSchema(schema)
    expect(result.$defs).toBeUndefined()
    expect(result.properties.name.type).toBe("string")
  })

  test("handles hardcoded schema with $ref (simulating MCP tool schema)", () => {
    // MCP servers can return JSON Schema with $ref
    const mcpSchema = {
      type: "object",
      properties: {
        query: { type: "string" },
        filters: {
          type: "array",
          items: { $ref: "#/$defs/Filter" },
        },
      },
      required: ["query"],
      $defs: {
        Filter: {
          type: "object",
          properties: {
            field: { type: "string" },
            operator: { type: "string", enum: ["eq", "ne", "gt", "lt"] },
            value: { type: "string" },
          },
          required: ["field", "operator", "value"],
        },
      },
    }

    const dereffed = ProviderTransform.derefJsonSchema(mcpSchema)
    console.log("MCP schema dereffed:", JSON.stringify(dereffed, null, 2))

    expect(JSON.stringify(dereffed).includes('"$ref"')).toBe(false)
    expect(dereffed.$defs).toBeUndefined()
    expect(dereffed.properties.filters.items.type).toBe("object")
    expect(dereffed.properties.filters.items.properties.field.type).toBe("string")
    expect(dereffed.properties.filters.items.properties.operator.enum).toEqual(["eq", "ne", "gt", "lt"])
  })
})
