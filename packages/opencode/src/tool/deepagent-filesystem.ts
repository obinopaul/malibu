import z from "zod"
import { Tool } from "./tool"
import { BashTool } from "./bash"
import { EditTool } from "./edit"
import { ListTool } from "./ls"
import { ReadTool } from "./read"
import { WriteTool } from "./write"
import { resolveDeepPath } from "./deepagent-path"

const LsParams = z.object({
  path: z.string().optional().describe("Directory path under the project root. Use '/' for the worktree root."),
})

export const LsTool = Tool.define("ls", async (init) => {
  const tool = await ListTool.init(init)
  return {
    description: "List files and directories under the project root.",
    parameters: LsParams,
    execute(args: z.infer<typeof LsParams>, ctx) {
      return tool.execute(
        {
          path: resolveDeepPath(args.path ?? "/", { strict: true }),
        },
        ctx,
      )
    },
  }
})

const ReadFileParams = z.object({
  file_path: z.string().describe("File path under the project root."),
  offset: z.coerce
    .number()
    .optional()
    .describe("Zero-indexed line offset. Converted to Malibu's one-indexed read API."),
  limit: z.coerce.number().optional().describe("Maximum number of lines to read."),
})

export const ReadFileTool = Tool.define("read_file", async (init) => {
  const tool = await ReadTool.init(init)
  return {
    description: "Read a file from the project root using Deep Agents path semantics.",
    parameters: ReadFileParams,
    execute(args: z.infer<typeof ReadFileParams>, ctx) {
      return tool.execute(
        {
          filePath: resolveDeepPath(args.file_path, { strict: true }),
          offset: args.offset === undefined ? undefined : args.offset + 1,
          limit: args.limit,
        },
        ctx,
      )
    },
  }
})

const WriteFileParams = z.object({
  file_path: z.string().describe("File path under the project root."),
  content: z.string().describe("File contents to write."),
})

export const WriteFileTool = Tool.define("write_file", async (init) => {
  const tool = await WriteTool.init(init)
  return {
    description: "Write a file under the project root using Deep Agents path semantics.",
    parameters: WriteFileParams,
    execute(args: z.infer<typeof WriteFileParams>, ctx) {
      return tool.execute(
        {
          filePath: resolveDeepPath(args.file_path, { strict: true }),
          content: args.content,
        },
        ctx,
      )
    },
  }
})

const EditFileParams = z.object({
  file_path: z.string().describe("File path under the project root."),
  old_string: z.string().describe("Text to replace."),
  new_string: z.string().describe("Replacement text."),
  replace_all: z.coerce.boolean().optional().describe("Replace every occurrence instead of one exact match."),
})

export const EditFileTool = Tool.define("edit_file", async (init) => {
  const tool = await EditTool.init(init)
  return {
    description: "Edit a file under the project root using Deep Agents path semantics.",
    parameters: EditFileParams,
    execute(args: z.infer<typeof EditFileParams>, ctx) {
      return tool.execute(
        {
          filePath: resolveDeepPath(args.file_path, { strict: true }),
          oldString: args.old_string,
          newString: args.new_string,
          replaceAll: args.replace_all,
        },
        ctx,
      )
    },
  }
})

const ExecuteParams = z.object({
  command: z.string().describe("Shell command to execute."),
  timeout: z.coerce.number().optional().describe("Optional timeout in milliseconds."),
  workdir: z.string().optional().describe("Optional working directory under the project root."),
})

export const ExecuteTool = Tool.define("execute", async (init) => {
  const tool = await BashTool.init(init)
  return {
    description: "Run a shell command with Malibu's bash tool.",
    parameters: ExecuteParams,
    execute(args: z.infer<typeof ExecuteParams>, ctx) {
      return tool.execute(
        {
          command: args.command,
          timeout: args.timeout,
          workdir: args.workdir ? resolveDeepPath(args.workdir, { strict: true }) : undefined,
          description: "Run shell command",
        },
        ctx,
      )
    },
  }
})
