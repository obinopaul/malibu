import { Config } from "effect"

function truthy(key: string) {
  const value = process.env[key]?.toLowerCase()
  return value === "true" || value === "1"
}

function falsy(key: string) {
  const value = process.env[key]?.toLowerCase()
  return value === "false" || value === "0"
}

export namespace Flag {
  export const MALIBU_AUTO_SHARE = truthy("MALIBU_AUTO_SHARE")
  export const MALIBU_GIT_BASH_PATH = process.env["MALIBU_GIT_BASH_PATH"]
  export const MALIBU_CONFIG = process.env["MALIBU_CONFIG"]
  export declare const MALIBU_TUI_CONFIG: string | undefined
  export declare const MALIBU_CONFIG_DIR: string | undefined
  export const MALIBU_CONFIG_CONTENT = process.env["MALIBU_CONFIG_CONTENT"]
  export const MALIBU_DISABLE_AUTOUPDATE = truthy("MALIBU_DISABLE_AUTOUPDATE")
  export const MALIBU_DISABLE_PRUNE = truthy("MALIBU_DISABLE_PRUNE")
  export const MALIBU_DISABLE_TERMINAL_TITLE = truthy("MALIBU_DISABLE_TERMINAL_TITLE")
  export const MALIBU_PERMISSION = process.env["MALIBU_PERMISSION"]
  export const MALIBU_DISABLE_DEFAULT_PLUGINS = truthy("MALIBU_DISABLE_DEFAULT_PLUGINS")
  export const MALIBU_DISABLE_LSP_DOWNLOAD = truthy("MALIBU_DISABLE_LSP_DOWNLOAD")
  export const MALIBU_ENABLE_EXPERIMENTAL_MODELS = truthy("MALIBU_ENABLE_EXPERIMENTAL_MODELS")
  export const MALIBU_DISABLE_AUTOCOMPACT = truthy("MALIBU_DISABLE_AUTOCOMPACT")
  export const MALIBU_DISABLE_MODELS_FETCH = truthy("MALIBU_DISABLE_MODELS_FETCH")
  export const MALIBU_DISABLE_CLAUDE_CODE = truthy("MALIBU_DISABLE_CLAUDE_CODE")
  export const MALIBU_DISABLE_CLAUDE_CODE_PROMPT =
    MALIBU_DISABLE_CLAUDE_CODE || truthy("MALIBU_DISABLE_CLAUDE_CODE_PROMPT")
  export const MALIBU_DISABLE_CLAUDE_CODE_SKILLS =
    MALIBU_DISABLE_CLAUDE_CODE || truthy("MALIBU_DISABLE_CLAUDE_CODE_SKILLS")
  export const MALIBU_DISABLE_EXTERNAL_SKILLS =
    MALIBU_DISABLE_CLAUDE_CODE_SKILLS || truthy("MALIBU_DISABLE_EXTERNAL_SKILLS")
  export declare const MALIBU_DISABLE_PROJECT_CONFIG: boolean
  export const MALIBU_FAKE_VCS = process.env["MALIBU_FAKE_VCS"]
  export declare const MALIBU_CLIENT: string
  export const MALIBU_SERVER_PASSWORD = process.env["MALIBU_SERVER_PASSWORD"]
  export const MALIBU_SERVER_USERNAME = process.env["MALIBU_SERVER_USERNAME"]
  export const MALIBU_ENABLE_QUESTION_TOOL = truthy("MALIBU_ENABLE_QUESTION_TOOL")

  // Experimental
  export const MALIBU_EXPERIMENTAL = truthy("MALIBU_EXPERIMENTAL")
  export const MALIBU_EXPERIMENTAL_FILEWATCHER = Config.boolean("MALIBU_EXPERIMENTAL_FILEWATCHER").pipe(
    Config.withDefault(false),
  )
  export const MALIBU_EXPERIMENTAL_DISABLE_FILEWATCHER = Config.boolean(
    "MALIBU_EXPERIMENTAL_DISABLE_FILEWATCHER",
  ).pipe(Config.withDefault(false))
  export const MALIBU_EXPERIMENTAL_ICON_DISCOVERY =
    MALIBU_EXPERIMENTAL || truthy("MALIBU_EXPERIMENTAL_ICON_DISCOVERY")

  const copy = process.env["MALIBU_EXPERIMENTAL_DISABLE_COPY_ON_SELECT"]
  export const MALIBU_EXPERIMENTAL_DISABLE_COPY_ON_SELECT =
    copy === undefined ? process.platform === "win32" : truthy("MALIBU_EXPERIMENTAL_DISABLE_COPY_ON_SELECT")
  export const MALIBU_ENABLE_EXA =
    truthy("MALIBU_ENABLE_EXA") || MALIBU_EXPERIMENTAL || truthy("MALIBU_EXPERIMENTAL_EXA")
  export const MALIBU_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS = number("MALIBU_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS")
  export const MALIBU_EXPERIMENTAL_OUTPUT_TOKEN_MAX = number("MALIBU_EXPERIMENTAL_OUTPUT_TOKEN_MAX")
  export const MALIBU_EXPERIMENTAL_OXFMT = MALIBU_EXPERIMENTAL || truthy("MALIBU_EXPERIMENTAL_OXFMT")
  export const MALIBU_EXPERIMENTAL_LSP_TY = truthy("MALIBU_EXPERIMENTAL_LSP_TY")
  export const MALIBU_EXPERIMENTAL_LSP_TOOL = MALIBU_EXPERIMENTAL || truthy("MALIBU_EXPERIMENTAL_LSP_TOOL")
  export const MALIBU_DISABLE_FILETIME_CHECK = Config.boolean("MALIBU_DISABLE_FILETIME_CHECK").pipe(
    Config.withDefault(false),
  )
  export const MALIBU_EXPERIMENTAL_PLAN_MODE = MALIBU_EXPERIMENTAL || truthy("MALIBU_EXPERIMENTAL_PLAN_MODE")
  export const MALIBU_EXPERIMENTAL_WORKSPACES = MALIBU_EXPERIMENTAL || truthy("MALIBU_EXPERIMENTAL_WORKSPACES")
  export const MALIBU_EXPERIMENTAL_MARKDOWN = !falsy("MALIBU_EXPERIMENTAL_MARKDOWN")
  export const MALIBU_MODELS_URL = process.env["MALIBU_MODELS_URL"]
  export const MALIBU_MODELS_PATH = process.env["MALIBU_MODELS_PATH"]
  export const MALIBU_DB = process.env["MALIBU_DB"]
  export const MALIBU_DISABLE_CHANNEL_DB = truthy("MALIBU_DISABLE_CHANNEL_DB")
  export const MALIBU_SKIP_MIGRATIONS = truthy("MALIBU_SKIP_MIGRATIONS")
  export const MALIBU_STRICT_CONFIG_DEPS = truthy("MALIBU_STRICT_CONFIG_DEPS")

  function number(key: string) {
    const value = process.env[key]
    if (!value) return undefined
    const parsed = Number(value)
    return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined
  }
}

// Dynamic getter for MALIBU_DISABLE_PROJECT_CONFIG
// This must be evaluated at access time, not module load time,
// because external tooling may set this env var at runtime
Object.defineProperty(Flag, "MALIBU_DISABLE_PROJECT_CONFIG", {
  get() {
    return truthy("MALIBU_DISABLE_PROJECT_CONFIG")
  },
  enumerable: true,
  configurable: false,
})

// Dynamic getter for MALIBU_TUI_CONFIG
// This must be evaluated at access time, not module load time,
// because tests and external tooling may set this env var at runtime
Object.defineProperty(Flag, "MALIBU_TUI_CONFIG", {
  get() {
    return process.env["MALIBU_TUI_CONFIG"]
  },
  enumerable: true,
  configurable: false,
})

// Dynamic getter for MALIBU_CONFIG_DIR
// This must be evaluated at access time, not module load time,
// because external tooling may set this env var at runtime
Object.defineProperty(Flag, "MALIBU_CONFIG_DIR", {
  get() {
    return process.env["MALIBU_CONFIG_DIR"]
  },
  enumerable: true,
  configurable: false,
})

// Dynamic getter for MALIBU_CLIENT
// This must be evaluated at access time, not module load time,
// because some commands override the client at runtime
Object.defineProperty(Flag, "MALIBU_CLIENT", {
  get() {
    return process.env["MALIBU_CLIENT"] ?? "cli"
  },
  enumerable: true,
  configurable: false,
})
