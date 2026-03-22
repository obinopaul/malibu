/**
 * AI SDK Adapter — wraps Vercel AI SDK LanguageModel instances
 * as LangChain BaseChatModel compatible objects.
 *
 * Used for custom providers (Copilot, GitLab, SAP, Cloudflare, LiteLLM)
 * that don't have native LangChain implementations.
 *
 * Now supports:
 * - Tool call streaming via fullStream (not just textStream)
 * - Usage metadata extraction from finish events
 * - Proper AIMessageChunk with tool_call_chunks for streaming
 */
import { BaseChatModel, type BindToolsInput } from "@langchain/core/language_models/chat_models"
import { AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage } from "@langchain/core/messages"
import { ChatGenerationChunk, type ChatResult } from "@langchain/core/outputs"
import type { CallbackManagerForLLMRun } from "@langchain/core/callbacks/manager"
import { convertToOpenAITool } from "@langchain/core/utils/function_calling"
import { streamText, generateText, tool as aiTool, type LanguageModel, type ModelMessage } from "ai"
import { jsonSchema } from "ai"
import { zodToJsonSchema } from "zod-to-json-schema"
import { Log } from "../util/log"

const log = Log.create({ service: "ai-sdk-adapter" })

/** Convert LangChain messages to Vercel AI SDK format */
function toAISDKMessages(messages: BaseMessage[]): ModelMessage[] {
  return messages.map((msg): ModelMessage => {
    if (msg instanceof SystemMessage) {
      return { role: "system", content: typeof msg.content === "string" ? msg.content : "" }
    }
    if (msg instanceof HumanMessage) {
      return { role: "user", content: typeof msg.content === "string" ? msg.content : "" }
    }
    if (msg instanceof AIMessage) {
      // Handle tool calls in assistant messages
      const toolCalls = msg.tool_calls ?? []
      if (toolCalls.length > 0) {
        return {
          role: "assistant",
          content: [
            ...(typeof msg.content === "string" && msg.content
              ? [{ type: "text" as const, text: msg.content }]
              : []),
            ...toolCalls.map((tc) => ({
              type: "tool-call" as const,
              toolCallId: tc.id ?? "",
              toolName: tc.name,
              args: tc.args,
            })),
          ],
        } as any
      }
      return { role: "assistant", content: typeof msg.content === "string" ? msg.content : "" }
    }
    if (msg instanceof ToolMessage) {
      return {
        role: "tool" as any,
        content: [
          {
            type: "tool-result" as any,
            toolCallId: msg.tool_call_id ?? "",
            toolName: msg.name ?? "",
            result: typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content),
          },
        ],
      } as any
    }
    return { role: "user", content: typeof msg.content === "string" ? msg.content : "" }
  })
}

export interface AISdkAdapterInput {
  model: LanguageModel
  providerID: string
  modelID: string
  temperature?: number
  maxTokens?: number
}

/**
 * LangChain-compatible wrapper around a Vercel AI SDK LanguageModel.
 * Enables custom providers (Copilot, GitLab, SAP) to be used
 * in LangChain/LangGraph agent pipelines.
 */
export class AISdkChatModel extends BaseChatModel {
  private aiModel: LanguageModel
  private providerID: string
  private modelID: string
  private temp?: number
  private maxTok?: number
  private boundTools?: Record<string, any>

  constructor(input: AISdkAdapterInput & { boundTools?: Record<string, any> }) {
    super({})
    this.aiModel = input.model
    this.providerID = input.providerID
    this.modelID = input.modelID
    this.temp = input.temperature
    this.maxTok = input.maxTokens
    this.boundTools = input.boundTools
  }

  override _llmType(): string {
    return `ai-sdk-${this.providerID}`
  }

  /**
   * Bind tools to this model for LangGraph's createReactAgent.
   * Converts LangChain tool definitions to AI SDK tool format and returns
   * a new AISdkChatModel instance that passes them to streamText()/generateText().
   *
   * Handles all BindToolsInput types: StructuredToolInterface, ToolDefinition,
   * RunnableToolLike, StructuredToolParams, and raw objects.
   */
  override bindTools(
    tools: BindToolsInput[],
    _kwargs?: Partial<this["ParsedCallOptions"]>,
  ): AISdkChatModel {
    const sdkTools: Record<string, any> = {}
    for (const t of tools) {
      try {
        // Use LangChain's convertToOpenAITool to normalize all input types
        // into a consistent { type: "function", function: { name, description, parameters } } format
        const openAITool = convertToOpenAITool(t)
        const fn = openAITool.function
        if (!fn?.name) continue

        const params = fn.parameters ?? { type: "object", properties: {} }
        sdkTools[fn.name] = aiTool({
          description: fn.description ?? "",
          inputSchema: jsonSchema(params as any),
        })
      } catch (e: any) {
        // Fallback: try to extract name/schema directly (e.g. raw objects)
        const toolDef = t as any
        const name = toolDef.name ?? toolDef.function?.name ?? ""
        if (!name) continue
        try {
          const schema = toolDef.schema ?? toolDef.function?.parameters
          if (schema) {
            // If it's a Zod schema, convert to JSON schema for AI SDK
            const jsonSchemaObj = typeof schema.parse === "function"
              ? zodToJsonSchema(schema)
              : schema
            sdkTools[name] = aiTool({
              description: toolDef.description ?? toolDef.function?.description ?? "",
              inputSchema: jsonSchema(jsonSchemaObj as any),
            })
          } else {
            sdkTools[name] = aiTool({
              description: toolDef.description ?? "",
              inputSchema: jsonSchema({ type: "object", properties: {} } as any),
            })
          }
        } catch (fallbackError: any) {
          log.warn("failed to convert tool for AI SDK binding", { name, error: fallbackError.message })
        }
      }
    }
    return new AISdkChatModel({
      model: this.aiModel,
      providerID: this.providerID,
      modelID: this.modelID,
      temperature: this.temp,
      maxTokens: this.maxTok,
      boundTools: sdkTools,
    })
  }

  /** Non-streaming generation */
  override async _generate(
    messages: BaseMessage[],
    _options: this["ParsedCallOptions"],
    _runManager?: CallbackManagerForLLMRun,
  ): Promise<ChatResult> {
    const sdkMessages = toAISDKMessages(messages)
    const result = await generateText({
      model: this.aiModel,
      messages: sdkMessages,
      temperature: this.temp,
      maxOutputTokens: this.maxTok,
      ...(this.boundTools ? { tools: this.boundTools } : {}),
    })

    const toolCalls = result.response.messages
      .flatMap((m: any) =>
        m.role === "assistant" && Array.isArray(m.content)
          ? m.content.filter((p: any) => p.type === "tool-call")
          : [],
      )
      .map((tc: any) => ({
        id: tc.toolCallId,
        name: tc.toolName,
        args: tc.args,
      }))

    const aiMessage = new AIMessage({
      content: result.text,
      tool_calls: toolCalls,
      usage_metadata: {
        input_tokens: (result.usage as any)?.promptTokens ?? 0,
        output_tokens: (result.usage as any)?.completionTokens ?? 0,
        total_tokens:
          ((result.usage as any)?.promptTokens ?? 0) +
          ((result.usage as any)?.completionTokens ?? 0),
      },
    })

    return {
      generations: [
        {
          message: aiMessage,
          text: result.text,
          generationInfo: {},
        },
      ],
      llmOutput: {
        tokenUsage: {
          promptTokens: (result.usage as any)?.promptTokens ?? 0,
          completionTokens: (result.usage as any)?.completionTokens ?? 0,
          totalTokens:
            ((result.usage as any)?.promptTokens ?? 0) +
            ((result.usage as any)?.completionTokens ?? 0),
        },
      },
    }
  }

  /**
   * Streaming generation — uses fullStream to capture both text and tool calls.
   *
   * Previously only used textStream which completely dropped tool calls.
   * Now handles:
   * - text-delta: incremental text chunks
   * - tool-call: complete tool call events
   * - tool-call-streaming-start/delta: streaming tool call arg accumulation
   * - finish: usage metadata extraction
   */
  override async *_streamResponseChunks(
    messages: BaseMessage[],
    _options: this["ParsedCallOptions"],
    _runManager?: CallbackManagerForLLMRun,
  ): AsyncGenerator<ChatGenerationChunk> {
    const sdkMessages = toAISDKMessages(messages)
    const result = streamText({
      model: this.aiModel,
      messages: sdkMessages,
      temperature: this.temp,
      maxOutputTokens: this.maxTok,
      ...(this.boundTools ? { tools: this.boundTools } : {}),
    })

    // Track streaming tool call state
    const pendingToolCalls = new Map<string, { name: string; argsText: string }>()

    for await (const part of result.fullStream) {
      switch (part.type) {
        case "text-delta": {
          const textDelta = (part as any).text ?? (part as any).textDelta ?? ""
          yield new ChatGenerationChunk({
            message: new AIMessageChunk({ content: textDelta }),
            text: textDelta,
          })
          break
        }

        case "tool-call": {
          // Complete tool call — emit as AIMessageChunk with tool_calls
          const toolPart = part as any
          const toolArgs = toolPart.args ?? toolPart.input ?? {}
          yield new ChatGenerationChunk({
            message: new AIMessageChunk({
              content: "",
              tool_calls: [
                {
                  id: toolPart.toolCallId,
                  name: toolPart.toolName,
                  args: toolArgs,
                },
              ],
              tool_call_chunks: [
                {
                  id: toolPart.toolCallId,
                  name: toolPart.toolName,
                  args: JSON.stringify(toolArgs),
                  index: 0,
                },
              ],
            }),
            text: "",
          })
          pendingToolCalls.delete(toolPart.toolCallId)
          break
        }

        case "tool-call-streaming-start" as any: {
          // Start of streaming tool call
          const p = part as any
          pendingToolCalls.set(p.toolCallId, { name: p.toolName, argsText: "" })
          yield new ChatGenerationChunk({
            message: new AIMessageChunk({
              content: "",
              tool_call_chunks: [
                {
                  id: p.toolCallId,
                  name: p.toolName,
                  args: "",
                  index: 0,
                },
              ],
            }),
            text: "",
          })
          break
        }

        case "tool-call-delta" as any: {
          // Streaming tool call args delta
          // IMPORTANT: Only set name/id on the first chunk (tool-call-streaming-start).
          // Setting them on every delta causes LangChain's AIMessageChunk.__add__()
          // to concatenate names (e.g., "read_fileread_file...") which breaks tool lookup.
          const p = part as any
          const pending = pendingToolCalls.get(p.toolCallId)
          if (pending) {
            pending.argsText += p.argsTextDelta ?? ""
          }
          yield new ChatGenerationChunk({
            message: new AIMessageChunk({
              content: "",
              tool_call_chunks: [
                {
                  id: undefined,
                  name: undefined,
                  args: p.argsTextDelta ?? "",
                  index: 0,
                },
              ],
            }),
            text: "",
          })
          break
        }

        case "finish": {
          // Extract usage metadata from finish event
          const usage = (part as any).usage
          if (usage) {
            yield new ChatGenerationChunk({
              message: new AIMessageChunk({
                content: "",
                usage_metadata: {
                  input_tokens: usage.promptTokens ?? 0,
                  output_tokens: usage.completionTokens ?? 0,
                  total_tokens: (usage.promptTokens ?? 0) + (usage.completionTokens ?? 0),
                },
              }),
              text: "",
            })
          }
          break
        }

        case "error": {
          log.error("ai-sdk stream error", { error: (part as any).error })
          break
        }

        default:
          // Ignore other stream parts (step-start, step-finish, etc.)
          break
      }
    }
  }
}
