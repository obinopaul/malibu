import {
  batch,
  createContext,
  createEffect,
  createMemo,
  createSignal,
  For,
  Match,
  on,
  onMount,
  Show,
  Switch,
  useContext,
} from "solid-js"
import { Dynamic } from "solid-js/web"
import path from "path"
import { useRoute, useRouteData } from "@tui/context/route"
import { useSync } from "@tui/context/sync"
import { SplitBorder } from "@tui/component/border"
import { Spinner } from "@tui/component/spinner"
import { selectedForeground, useTheme } from "@tui/context/theme"
import {
  BoxRenderable,
  ScrollBoxRenderable,
  addDefaultParsers,
  MacOSScrollAccel,
  type ScrollAcceleration,
  TextAttributes,
  RGBA,
} from "@opentui/core"
import { Prompt, type PromptRef } from "@tui/component/prompt"
import type { AssistantMessage, Part, ToolPart, UserMessage, TextPart, ReasoningPart } from "@malibu-ai/sdk/v2"
import { useLocal } from "@tui/context/local"
import { Locale } from "@/util/locale"
import type { Tool } from "@/tool/tool"
import type { ReadTool } from "@/tool/read"
import type { WriteTool } from "@/tool/write"
import { BashTool } from "@/tool/bash"
import type { GlobTool } from "@/tool/glob"
import { TodoWriteTool } from "@/tool/todo"
import type { GrepTool } from "@/tool/grep"
import type { ListTool } from "@/tool/ls"
import type { EditTool } from "@/tool/edit"
import type { ApplyPatchTool } from "@/tool/apply_patch"
import type { WebFetchTool } from "@/tool/webfetch"
import type { TaskTool } from "@/tool/task"
import type { QuestionTool } from "@/tool/question"
import type { SkillTool } from "@/tool/skill"
import { useKeyboard, useRenderer, useTerminalDimensions, type JSX } from "@opentui/solid"
import { useSDK } from "@tui/context/sdk"
import { useCommandDialog } from "@tui/component/dialog-command"
import type { DialogContext } from "@tui/ui/dialog"
import { useKeybind } from "@tui/context/keybind"
import { Header } from "./header"
import { parsePatch } from "diff"
import { useDialog } from "../../ui/dialog"
import { TodoItem } from "../../component/todo-item"
import { DialogMessage } from "./dialog-message"
import type { PromptInfo } from "../../component/prompt/history"
import { DialogConfirm } from "@tui/ui/dialog-confirm"
import { DialogTimeline } from "./dialog-timeline"
import { DialogForkFromTimeline } from "./dialog-fork-from-timeline"
import { DialogSessionRename } from "../../component/dialog-session-rename"
import { Sidebar } from "./sidebar"
import { Flag } from "@/flag/flag"
import { LANGUAGE_EXTENSIONS } from "@/lsp/language"
import parsers from "../../../../../../parsers-config.ts"
import { Clipboard } from "../../util/clipboard"
import { Toast, useToast } from "../../ui/toast"
import { useKV } from "../../context/kv.tsx"
import { Editor } from "../../util/editor"
import stripAnsi from "strip-ansi"
import { Footer } from "./footer.tsx"
import { usePromptRef } from "../../context/prompt"
import { useExit } from "../../context/exit"
import { useExitGuard } from "../../hooks/use-exit-guard"
import { Filesystem } from "@/util/filesystem"
import { Global } from "@/global"
import { PermissionPrompt } from "./permission"
import { QuestionPrompt } from "./question"
import { DialogExportOptions } from "../../ui/dialog-export-options"
import { formatTranscript } from "../../util/transcript"
import { UI } from "@/cli/ui.ts"
import { useTuiConfig } from "../../context/tui-config"

addDefaultParsers(parsers.parsers)

class CustomSpeedScroll implements ScrollAcceleration {
  constructor(private speed: number) {}

  tick(_now?: number): number {
    return this.speed
  }

  reset(): void {}
}

const context = createContext<{
  width: number
  sessionID: string
  conceal: () => boolean
  showThinking: () => boolean
  showTimestamps: () => boolean
  showDetails: () => boolean
  showGenericToolOutput: () => boolean
  diffWrapMode: () => "word" | "none"
  sync: ReturnType<typeof useSync>
  tui: ReturnType<typeof useTuiConfig>
}>()

function use() {
  const ctx = useContext(context)
  if (!ctx) throw new Error("useContext must be used within a Session component")
  return ctx
}

export function Session() {
  const route = useRouteData("session")
  const { navigate } = useRoute()
  const sync = useSync()
  const tuiConfig = useTuiConfig()
  const kv = useKV()
  const { theme } = useTheme()
  const promptRef = usePromptRef()
  const session = createMemo(() => sync.session.get(route.sessionID))
  const children = createMemo(() => {
    const parentID = session()?.parentID ?? session()?.id
    return sync.data.session
      .filter((x) => x.parentID === parentID || x.id === parentID)
      .toSorted((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
  })
  const messages = createMemo(() => sync.data.message[route.sessionID] ?? [])
  const permissions = createMemo(() => {
    if (session()?.parentID) return []
    return children().flatMap((x) => sync.data.permission[x.id] ?? [])
  })
  const questions = createMemo(() => {
    if (session()?.parentID) return []
    return children().flatMap((x) => sync.data.question[x.id] ?? [])
  })

  const pending = createMemo(() => {
    return messages().findLast((x) => x.role === "assistant" && !x.time.completed)?.id
  })

  const lastAssistant = createMemo(() => {
    return messages().findLast((x) => x.role === "assistant")
  })

  const dimensions = useTerminalDimensions()
  const [sidebar, setSidebar] = kv.signal<"auto" | "hide">("sidebar", "auto")
  const [sidebarOpen, setSidebarOpen] = createSignal(false)
  const [conceal, setConceal] = createSignal(true)
  const [showThinking, setShowThinking] = kv.signal("thinking_visibility", true)
  const [timestamps, setTimestamps] = kv.signal<"hide" | "show">("timestamps", "hide")
  const [showDetails, setShowDetails] = kv.signal("tool_details_visibility", true)
  const [showAssistantMetadata, setShowAssistantMetadata] = kv.signal("assistant_metadata_visibility", true)
  const [showScrollbar, setShowScrollbar] = kv.signal("scrollbar_visible", true)
  const [showHeader, setShowHeader] = kv.signal("header_visible", true)
  const [diffWrapMode] = kv.signal<"word" | "none">("diff_wrap_mode", "word")
  const [animationsEnabled, setAnimationsEnabled] = kv.signal("animations_enabled", true)
  const [showGenericToolOutput, setShowGenericToolOutput] = kv.signal("generic_tool_output_visibility", false)

  const wide = createMemo(() => dimensions().width > 120)
  const sidebarVisible = createMemo(() => {
    if (session()?.parentID) return false
    if (sidebarOpen()) return true
    if (sidebar() === "auto" && wide()) return true
    return false
  })
  const showTimestamps = createMemo(() => timestamps() === "show")
  const contentWidth = createMemo(() => dimensions().width - (sidebarVisible() ? 42 : 0) - 4)

  const scrollAcceleration = createMemo(() => {
    const tui = tuiConfig
    if (tui?.scroll_acceleration?.enabled) {
      return new MacOSScrollAccel()
    }
    if (tui?.scroll_speed) {
      return new CustomSpeedScroll(tui.scroll_speed)
    }

    return new CustomSpeedScroll(3)
  })

  createEffect(() => {
    if (session()?.workspaceID) {
      sdk.setWorkspace(session()?.workspaceID)
    }
  })

  createEffect(async () => {
    await sync.session
      .sync(route.sessionID)
      .then(() => {
        if (scroll) scroll.scrollBy(100_000)
      })
      .catch((e) => {
        console.error(e)
        toast.show({
          message: `Session not found: ${route.sessionID}`,
          variant: "error",
        })
        return navigate({ type: "home" })
      })
  })

  const toast = useToast()
  const sdk = useSDK()

  // Handle initial prompt from fork
  createEffect(() => {
    if (route.initialPrompt && prompt) {
      prompt.set(route.initialPrompt)
    }
  })

  let lastSwitch: string | undefined = undefined
  sdk.event.on("message.part.updated", (evt) => {
    const part = evt.properties.part
    if (part.type !== "tool") return
    if (part.sessionID !== route.sessionID) return
    if (part.state.status !== "completed") return
    if (part.id === lastSwitch) return

    if (part.tool === "plan_exit") {
      local.agent.set("build")
      lastSwitch = part.id
    } else if (part.tool === "plan_enter") {
      local.agent.set("plan")
      lastSwitch = part.id
    }
  })

  let scroll: ScrollBoxRenderable
  let prompt: PromptRef
  const keybind = useKeybind()
  const dialog = useDialog()
  const renderer = useRenderer()

  // Allow exit when in child session (prompt is hidden)
  const exit = useExit()
  const exitGuard = useExitGuard()

  createEffect(() => {
    const title = Locale.truncate(session()?.title ?? "", 50)
    const pad = (text: string) => text.padEnd(10, " ")
    const weak = (text: string) => UI.Style.TEXT_DIM + pad(text) + UI.Style.TEXT_NORMAL
    const logo = UI.logo("  ").split(/\r?\n/)
    return exit.message.set(
      [
        `${logo[0] ?? ""}`,
        `${logo[1] ?? ""}`,
        `${logo[2] ?? ""}`,
        `${logo[3] ?? ""}`,
        ``,
        `  ${weak("Session")}${UI.Style.TEXT_NORMAL_BOLD}${title}${UI.Style.TEXT_NORMAL}`,
        `  ${weak("Continue")}${UI.Style.TEXT_NORMAL_BOLD}malibu -s ${session()?.id}${UI.Style.TEXT_NORMAL}`,
        ``,
      ].join("\n"),
    )
  })

  useKeyboard((evt) => {
    if (!session()?.parentID) return
    if (keybind.match("app_exit", evt)) {
      exitGuard.tryExit()
    }
  })

  // Helper: Find next visible message boundary in direction
  const findNextVisibleMessage = (direction: "next" | "prev"): string | null => {
    const children = scroll.getChildren()
    const messagesList = messages()
    const scrollTop = scroll.y

    // Get visible messages sorted by position, filtering for valid non-synthetic, non-ignored content
    const visibleMessages = children
      .filter((c) => {
        if (!c.id) return false
        const message = messagesList.find((m) => m.id === c.id)
        if (!message) return false

        // Check if message has valid non-synthetic, non-ignored text parts
        const parts = sync.data.part[message.id]
        if (!parts || !Array.isArray(parts)) return false

        return parts.some((part) => part && part.type === "text" && !part.synthetic && !part.ignored)
      })
      .sort((a, b) => a.y - b.y)

    if (visibleMessages.length === 0) return null

    if (direction === "next") {
      // Find first message below current position
      return visibleMessages.find((c) => c.y > scrollTop + 10)?.id ?? null
    }
    // Find last message above current position
    return [...visibleMessages].reverse().find((c) => c.y < scrollTop - 10)?.id ?? null
  }

  // Helper: Scroll to message in direction or fallback to page scroll
  const scrollToMessage = (direction: "next" | "prev", dialog: ReturnType<typeof useDialog>) => {
    const targetID = findNextVisibleMessage(direction)

    if (!targetID) {
      scroll.scrollBy(direction === "next" ? scroll.height : -scroll.height)
      dialog.clear()
      return
    }

    const child = scroll.getChildren().find((c) => c.id === targetID)
    if (child) scroll.scrollBy(child.y - scroll.y - 1)
    dialog.clear()
  }

  function toBottom() {
    setTimeout(() => {
      if (!scroll || scroll.isDestroyed) return
      scroll.scrollTo(scroll.scrollHeight)
    }, 50)
  }

  const local = useLocal()

  function moveFirstChild() {
    if (children().length === 1) return
    const next = children().find((x) => !!x.parentID)
    if (next) {
      navigate({
        type: "session",
        sessionID: next.id,
      })
    }
  }

  function moveChild(direction: number) {
    if (children().length === 1) return

    const sessions = children().filter((x) => !!x.parentID)
    let next = sessions.findIndex((x) => x.id === session()?.id) + direction

    if (next >= sessions.length) next = 0
    if (next < 0) next = sessions.length - 1
    if (sessions[next]) {
      navigate({
        type: "session",
        sessionID: sessions[next].id,
      })
    }
  }

  function childSessionHandler(func: (dialog: DialogContext) => void) {
    return (dialog: DialogContext) => {
      if (!session()?.parentID || dialog.stack.length > 0) return
      func(dialog)
    }
  }

  const command = useCommandDialog()
  command.register(() => [
    {
      title: session()?.share?.url ? "Copy share link" : "Share session",
      value: "session.share",
      suggested: route.type === "session",
      keybind: "session_share",
      category: "Session",
      enabled: sync.data.config.share !== "disabled",
      slash: {
        name: "share",
      },
      onSelect: async (dialog) => {
        const copy = (url: string) =>
          Clipboard.copy(url)
            .then(() => toast.show({ message: "Share URL copied to clipboard!", variant: "success" }))
            .catch(() => toast.show({ message: "Failed to copy URL to clipboard", variant: "error" }))
        const url = session()?.share?.url
        if (url) {
          await copy(url)
          dialog.clear()
          return
        }
        await sdk.client.session
          .share({
            sessionID: route.sessionID,
          })
          .then((res) => copy(res.data!.share!.url))
          .catch((error) => {
            toast.show({
              message: error instanceof Error ? error.message : "Failed to share session",
              variant: "error",
            })
          })
        dialog.clear()
      },
    },
    {
      title: "Rename session",
      value: "session.rename",
      keybind: "session_rename",
      category: "Session",
      slash: {
        name: "rename",
      },
      onSelect: (dialog) => {
        dialog.replace(() => <DialogSessionRename session={route.sessionID} />)
      },
    },
    {
      title: "Jump to message",
      value: "session.timeline",
      keybind: "session_timeline",
      category: "Session",
      slash: {
        name: "timeline",
      },
      onSelect: (dialog) => {
        dialog.replace(() => (
          <DialogTimeline
            onMove={(messageID) => {
              const child = scroll.getChildren().find((child) => {
                return child.id === messageID
              })
              if (child) scroll.scrollBy(child.y - scroll.y - 1)
            }}
            sessionID={route.sessionID}
            setPrompt={(promptInfo) => prompt.set(promptInfo)}
          />
        ))
      },
    },
    {
      title: "Fork from message",
      value: "session.fork",
      keybind: "session_fork",
      category: "Session",
      slash: {
        name: "fork",
      },
      onSelect: (dialog) => {
        dialog.replace(() => (
          <DialogForkFromTimeline
            onMove={(messageID) => {
              const child = scroll.getChildren().find((child) => {
                return child.id === messageID
              })
              if (child) scroll.scrollBy(child.y - scroll.y - 1)
            }}
            sessionID={route.sessionID}
          />
        ))
      },
    },
    {
      title: "Compact session",
      value: "session.compact",
      keybind: "session_compact",
      category: "Session",
      slash: {
        name: "compact",
        aliases: ["summarize"],
      },
      onSelect: (dialog) => {
        const selectedModel = local.model.current()
        if (!selectedModel) {
          toast.show({
            variant: "warning",
            message: "Connect a provider to summarize this session",
            duration: 3000,
          })
          return
        }
        sdk.client.session.summarize({
          sessionID: route.sessionID,
          modelID: selectedModel.modelID,
          providerID: selectedModel.providerID,
        })
        dialog.clear()
      },
    },
    {
      title: "Unshare session",
      value: "session.unshare",
      keybind: "session_unshare",
      category: "Session",
      enabled: !!session()?.share?.url,
      slash: {
        name: "unshare",
      },
      onSelect: async (dialog) => {
        await sdk.client.session
          .unshare({
            sessionID: route.sessionID,
          })
          .then(() => toast.show({ message: "Session unshared successfully", variant: "success" }))
          .catch((error) => {
            toast.show({
              message: error instanceof Error ? error.message : "Failed to unshare session",
              variant: "error",
            })
          })
        dialog.clear()
      },
    },
    {
      title: "Undo previous message",
      value: "session.undo",
      keybind: "messages_undo",
      category: "Session",
      slash: {
        name: "undo",
      },
      onSelect: async (dialog) => {
        const status = sync.data.session_status?.[route.sessionID]
        if (status?.type !== "idle") await sdk.client.session.abort({ sessionID: route.sessionID }).catch(() => {})
        const revert = session()?.revert?.messageID
        const message = messages().findLast((x) => (!revert || x.id < revert) && x.role === "user")
        if (!message) return
        sdk.client.session
          .revert({
            sessionID: route.sessionID,
            messageID: message.id,
          })
          .then(() => {
            toBottom()
          })
        const parts = sync.data.part[message.id]
        prompt.set(
          parts.reduce(
            (agg, part) => {
              if (part.type === "text") {
                if (!part.synthetic) agg.input += part.text
              }
              if (part.type === "file") agg.parts.push(part)
              return agg
            },
            { input: "", parts: [] as PromptInfo["parts"] },
          ),
        )
        dialog.clear()
      },
    },
    {
      title: "Redo",
      value: "session.redo",
      keybind: "messages_redo",
      category: "Session",
      enabled: !!session()?.revert?.messageID,
      slash: {
        name: "redo",
      },
      onSelect: (dialog) => {
        dialog.clear()
        const messageID = session()?.revert?.messageID
        if (!messageID) return
        const message = messages().find((x) => x.role === "user" && x.id > messageID)
        if (!message) {
          sdk.client.session.unrevert({
            sessionID: route.sessionID,
          })
          prompt.set({ input: "", parts: [] })
          return
        }
        sdk.client.session.revert({
          sessionID: route.sessionID,
          messageID: message.id,
        })
      },
    },
    {
      title: sidebarVisible() ? "Hide sidebar" : "Show sidebar",
      value: "session.sidebar.toggle",
      keybind: "sidebar_toggle",
      category: "Session",
      onSelect: (dialog) => {
        batch(() => {
          const isVisible = sidebarVisible()
          setSidebar(() => (isVisible ? "hide" : "auto"))
          setSidebarOpen(!isVisible)
        })
        dialog.clear()
      },
    },
    {
      title: conceal() ? "Disable code concealment" : "Enable code concealment",
      value: "session.toggle.conceal",
      keybind: "messages_toggle_conceal" as any,
      category: "Session",
      onSelect: (dialog) => {
        setConceal((prev) => !prev)
        dialog.clear()
      },
    },
    {
      title: showTimestamps() ? "Hide timestamps" : "Show timestamps",
      value: "session.toggle.timestamps",
      category: "Session",
      slash: {
        name: "timestamps",
        aliases: ["toggle-timestamps"],
      },
      onSelect: (dialog) => {
        setTimestamps((prev) => (prev === "show" ? "hide" : "show"))
        dialog.clear()
      },
    },
    {
      title: showThinking() ? "Hide thinking" : "Show thinking",
      value: "session.toggle.thinking",
      keybind: "display_thinking",
      category: "Session",
      slash: {
        name: "thinking",
        aliases: ["toggle-thinking"],
      },
      onSelect: (dialog) => {
        setShowThinking((prev) => !prev)
        dialog.clear()
      },
    },
    {
      title: showDetails() ? "Hide tool details" : "Show tool details",
      value: "session.toggle.actions",
      keybind: "tool_details",
      category: "Session",
      onSelect: (dialog) => {
        setShowDetails((prev) => !prev)
        dialog.clear()
      },
    },
    {
      title: "Toggle session scrollbar",
      value: "session.toggle.scrollbar",
      keybind: "scrollbar_toggle",
      category: "Session",
      onSelect: (dialog) => {
        setShowScrollbar((prev) => !prev)
        dialog.clear()
      },
    },
    {
      title: showHeader() ? "Hide header" : "Show header",
      value: "session.toggle.header",
      category: "Session",
      onSelect: (dialog) => {
        setShowHeader((prev) => !prev)
        dialog.clear()
      },
    },
    {
      title: showGenericToolOutput() ? "Hide generic tool output" : "Show generic tool output",
      value: "session.toggle.generic_tool_output",
      category: "Session",
      onSelect: (dialog) => {
        setShowGenericToolOutput((prev) => !prev)
        dialog.clear()
      },
    },
    {
      title: "Page up",
      value: "session.page.up",
      keybind: "messages_page_up",
      category: "Session",
      hidden: true,
      onSelect: (dialog) => {
        scroll.scrollBy(-scroll.height / 2)
        dialog.clear()
      },
    },
    {
      title: "Page down",
      value: "session.page.down",
      keybind: "messages_page_down",
      category: "Session",
      hidden: true,
      onSelect: (dialog) => {
        scroll.scrollBy(scroll.height / 2)
        dialog.clear()
      },
    },
    {
      title: "Line up",
      value: "session.line.up",
      keybind: "messages_line_up",
      category: "Session",
      disabled: true,
      onSelect: (dialog) => {
        scroll.scrollBy(-1)
        dialog.clear()
      },
    },
    {
      title: "Line down",
      value: "session.line.down",
      keybind: "messages_line_down",
      category: "Session",
      disabled: true,
      onSelect: (dialog) => {
        scroll.scrollBy(1)
        dialog.clear()
      },
    },
    {
      title: "Half page up",
      value: "session.half.page.up",
      keybind: "messages_half_page_up",
      category: "Session",
      hidden: true,
      onSelect: (dialog) => {
        scroll.scrollBy(-scroll.height / 4)
        dialog.clear()
      },
    },
    {
      title: "Half page down",
      value: "session.half.page.down",
      keybind: "messages_half_page_down",
      category: "Session",
      hidden: true,
      onSelect: (dialog) => {
        scroll.scrollBy(scroll.height / 4)
        dialog.clear()
      },
    },
    {
      title: "First message",
      value: "session.first",
      keybind: "messages_first",
      category: "Session",
      hidden: true,
      onSelect: (dialog) => {
        scroll.scrollTo(0)
        dialog.clear()
      },
    },
    {
      title: "Last message",
      value: "session.last",
      keybind: "messages_last",
      category: "Session",
      hidden: true,
      onSelect: (dialog) => {
        scroll.scrollTo(scroll.scrollHeight)
        dialog.clear()
      },
    },
    {
      title: "Jump to last user message",
      value: "session.messages_last_user",
      keybind: "messages_last_user",
      category: "Session",
      hidden: true,
      onSelect: () => {
        const messages = sync.data.message[route.sessionID]
        if (!messages || !messages.length) return

        // Find the most recent user message with non-ignored, non-synthetic text parts
        for (let i = messages.length - 1; i >= 0; i--) {
          const message = messages[i]
          if (!message || message.role !== "user") continue

          const parts = sync.data.part[message.id]
          if (!parts || !Array.isArray(parts)) continue

          const hasValidTextPart = parts.some(
            (part) => part && part.type === "text" && !part.synthetic && !part.ignored,
          )

          if (hasValidTextPart) {
            const child = scroll.getChildren().find((child) => {
              return child.id === message.id
            })
            if (child) scroll.scrollBy(child.y - scroll.y - 1)
            break
          }
        }
      },
    },
    {
      title: "Next message",
      value: "session.message.next",
      keybind: "messages_next",
      category: "Session",
      hidden: true,
      onSelect: (dialog) => scrollToMessage("next", dialog),
    },
    {
      title: "Previous message",
      value: "session.message.previous",
      keybind: "messages_previous",
      category: "Session",
      hidden: true,
      onSelect: (dialog) => scrollToMessage("prev", dialog),
    },
    {
      title: "Copy last assistant message",
      value: "messages.copy",
      keybind: "messages_copy",
      category: "Session",
      onSelect: (dialog) => {
        const revertID = session()?.revert?.messageID
        const lastAssistantMessage = messages().findLast(
          (msg) => msg.role === "assistant" && (!revertID || msg.id < revertID),
        )
        if (!lastAssistantMessage) {
          toast.show({ message: "No assistant messages found", variant: "error" })
          dialog.clear()
          return
        }

        const parts = sync.data.part[lastAssistantMessage.id] ?? []
        const textParts = parts.filter((part) => part.type === "text")
        if (textParts.length === 0) {
          toast.show({ message: "No text parts found in last assistant message", variant: "error" })
          dialog.clear()
          return
        }

        const text = textParts
          .map((part) => part.text)
          .join("\n")
          .trim()
        if (!text) {
          toast.show({
            message: "No text content found in last assistant message",
            variant: "error",
          })
          dialog.clear()
          return
        }

        Clipboard.copy(text)
          .then(() => toast.show({ message: "Message copied to clipboard!", variant: "success" }))
          .catch(() => toast.show({ message: "Failed to copy to clipboard", variant: "error" }))
        dialog.clear()
      },
    },
    {
      title: "Copy session transcript",
      value: "session.copy",
      category: "Session",
      slash: {
        name: "copy",
      },
      onSelect: async (dialog) => {
        try {
          const sessionData = session()
          if (!sessionData) return
          const sessionMessages = messages()
          const transcript = formatTranscript(
            sessionData,
            sessionMessages.map((msg) => ({ info: msg, parts: sync.data.part[msg.id] ?? [] })),
            {
              thinking: showThinking(),
              toolDetails: showDetails(),
              assistantMetadata: showAssistantMetadata(),
            },
          )
          await Clipboard.copy(transcript)
          toast.show({ message: "Session transcript copied to clipboard!", variant: "success" })
        } catch (error) {
          toast.show({ message: "Failed to copy session transcript", variant: "error" })
        }
        dialog.clear()
      },
    },
    {
      title: "Export session transcript",
      value: "session.export",
      keybind: "session_export",
      category: "Session",
      slash: {
        name: "export",
      },
      onSelect: async (dialog) => {
        try {
          const sessionData = session()
          if (!sessionData) return
          const sessionMessages = messages()

          const defaultFilename = `session-${sessionData.id.slice(0, 8)}.md`

          const options = await DialogExportOptions.show(
            dialog,
            defaultFilename,
            showThinking(),
            showDetails(),
            showAssistantMetadata(),
            false,
          )

          if (options === null) return

          const transcript = formatTranscript(
            sessionData,
            sessionMessages.map((msg) => ({ info: msg, parts: sync.data.part[msg.id] ?? [] })),
            {
              thinking: options.thinking,
              toolDetails: options.toolDetails,
              assistantMetadata: options.assistantMetadata,
            },
          )

          if (options.openWithoutSaving) {
            // Just open in editor without saving
            await Editor.open({ value: transcript, renderer })
          } else {
            const exportDir = process.cwd()
            const filename = options.filename.trim()
            const filepath = path.join(exportDir, filename)

            await Filesystem.write(filepath, transcript)

            // Open with EDITOR if available
            const result = await Editor.open({ value: transcript, renderer })
            if (result !== undefined) {
              await Filesystem.write(filepath, result)
            }

            toast.show({ message: `Session exported to ${filename}`, variant: "success" })
          }
        } catch (error) {
          toast.show({ message: "Failed to export session", variant: "error" })
        }
        dialog.clear()
      },
    },
    {
      title: "Go to child session",
      value: "session.child.first",
      keybind: "session_child_first",
      category: "Session",
      hidden: true,
      onSelect: (dialog) => {
        moveFirstChild()
        dialog.clear()
      },
    },
    {
      title: "Go to parent session",
      value: "session.parent",
      keybind: "session_parent",
      category: "Session",
      hidden: true,
      enabled: !!session()?.parentID,
      onSelect: childSessionHandler((dialog) => {
        const parentID = session()?.parentID
        if (parentID) {
          navigate({
            type: "session",
            sessionID: parentID,
          })
        }
        dialog.clear()
      }),
    },
    {
      title: "Next child session",
      value: "session.child.next",
      keybind: "session_child_cycle",
      category: "Session",
      hidden: true,
      enabled: !!session()?.parentID,
      onSelect: childSessionHandler((dialog) => {
        moveChild(1)
        dialog.clear()
      }),
    },
    {
      title: "Previous child session",
      value: "session.child.previous",
      keybind: "session_child_cycle_reverse",
      category: "Session",
      hidden: true,
      enabled: !!session()?.parentID,
      onSelect: childSessionHandler((dialog) => {
        moveChild(-1)
        dialog.clear()
      }),
    },
  ])

  const revertInfo = createMemo(() => session()?.revert)
  const revertMessageID = createMemo(() => revertInfo()?.messageID)

  const revertDiffFiles = createMemo(() => {
    const diffText = revertInfo()?.diff ?? ""
    if (!diffText) return []

    try {
      const patches = parsePatch(diffText)
      return patches.map((patch) => {
        const filename = patch.newFileName || patch.oldFileName || "unknown"
        const cleanFilename = filename.replace(/^[ab]\//, "")
        return {
          filename: cleanFilename,
          additions: patch.hunks.reduce(
            (sum, hunk) => sum + hunk.lines.filter((line) => line.startsWith("+")).length,
            0,
          ),
          deletions: patch.hunks.reduce(
            (sum, hunk) => sum + hunk.lines.filter((line) => line.startsWith("-")).length,
            0,
          ),
        }
      })
    } catch (error) {
      return []
    }
  })

  const revertRevertedMessages = createMemo(() => {
    const messageID = revertMessageID()
    if (!messageID) return []
    return messages().filter((x) => x.id >= messageID && x.role === "user")
  })

  const revert = createMemo(() => {
    const info = revertInfo()
    if (!info) return
    if (!info.messageID) return
    return {
      messageID: info.messageID,
      reverted: revertRevertedMessages(),
      diff: info.diff,
      diffFiles: revertDiffFiles(),
    }
  })

  // snap to bottom when session changes
  createEffect(on(() => route.sessionID, toBottom))

  return (
    <context.Provider
      value={{
        get width() {
          return contentWidth()
        },
        sessionID: route.sessionID,
        conceal,
        showThinking,
        showTimestamps,
        showDetails,
        showGenericToolOutput,
        diffWrapMode,
        sync,
        tui: tuiConfig,
      }}
    >
      <box flexDirection="row">
        <box flexGrow={1} paddingBottom={1} paddingTop={1} paddingLeft={2} paddingRight={2} gap={1}>
          <Show when={session()}>
            <Show when={showHeader() && (!sidebarVisible() || !wide())}>
              <Header />
            </Show>
            <scrollbox
              ref={(r) => (scroll = r)}
              viewportOptions={{
                paddingRight: showScrollbar() ? 1 : 0,
              }}
              verticalScrollbarOptions={{
                paddingLeft: 1,
                visible: showScrollbar(),
                trackOptions: {
                  backgroundColor: theme.backgroundElement,
                  foregroundColor: theme.border,
                },
              }}
              stickyScroll={true}
              stickyStart="bottom"
              flexGrow={1}
              scrollAcceleration={scrollAcceleration()}
            >
              <For each={messages()}>
                {(message, index) => (
                  <Switch>
                    <Match when={message.id === revert()?.messageID}>
                      {(function () {
                        const command = useCommandDialog()
                        const [hover, setHover] = createSignal(false)
                        const dialog = useDialog()

                        const handleUnrevert = async () => {
                          const confirmed = await DialogConfirm.show(
                            dialog,
                            "Confirm Redo",
                            "Are you sure you want to restore the reverted messages?",
                          )
                          if (confirmed) {
                            command.trigger("session.redo")
                          }
                        }

                        return (
                          <box
                            onMouseOver={() => setHover(true)}
                            onMouseOut={() => setHover(false)}
                            onMouseUp={handleUnrevert}
                            marginTop={1}
                            flexShrink={0}
                            border={["left"]}
                            customBorderChars={SplitBorder.customBorderChars}
                            borderColor={theme.backgroundPanel}
                          >
                            <box
                              paddingTop={1}
                              paddingBottom={1}
                              paddingLeft={2}
                              backgroundColor={hover() ? theme.backgroundElement : theme.backgroundPanel}
                            >
                              <text fg={theme.textMuted}>{revert()!.reverted.length} message reverted</text>
                              <text fg={theme.textMuted}>
                                <span style={{ fg: theme.text }}>{keybind.print("messages_redo")}</span> or /redo to
                                restore
                              </text>
                              <Show when={revert()!.diffFiles?.length}>
                                <box marginTop={1}>
                                  <For each={revert()!.diffFiles}>
                                    {(file) => (
                                      <text fg={theme.text}>
                                        {file.filename}
                                        <Show when={file.additions > 0}>
                                          <span style={{ fg: theme.diffAdded }}> +{file.additions}</span>
                                        </Show>
                                        <Show when={file.deletions > 0}>
                                          <span style={{ fg: theme.diffRemoved }}> -{file.deletions}</span>
                                        </Show>
                                      </text>
                                    )}
                                  </For>
                                </box>
                              </Show>
                            </box>
                          </box>
                        )
                      })()}
                    </Match>
                    <Match when={revert()?.messageID && message.id >= revert()!.messageID}>
                      <></>
                    </Match>
                    <Match when={message.role === "user"}>
                      <UserMessage
                        index={index()}
                        onMouseUp={() => {
                          if (renderer.getSelection()?.getSelectedText()) return
                          dialog.replace(() => (
                            <DialogMessage
                              messageID={message.id}
                              sessionID={route.sessionID}
                              setPrompt={(promptInfo) => prompt.set(promptInfo)}
                            />
                          ))
                        }}
                        message={message as UserMessage}
                        parts={sync.data.part[message.id] ?? []}
                        pending={pending()}
                      />
                    </Match>
                    <Match when={message.role === "assistant"}>
                      <AssistantMessage
                        last={lastAssistant()?.id === message.id}
                        message={message as AssistantMessage}
                        parts={sync.data.part[message.id] ?? []}
                      />
                    </Match>
                  </Switch>
                )}
              </For>
            </scrollbox>
            <box flexShrink={0}>
              <Show when={permissions().length > 0}>
                <PermissionPrompt request={permissions()[0]} />
              </Show>
              <Show when={permissions().length === 0 && questions().length > 0}>
                <QuestionPrompt request={questions()[0]} />
              </Show>
              <Prompt
                visible={!session()?.parentID && permissions().length === 0 && questions().length === 0}
                ref={(r) => {
                  prompt = r
                  promptRef.set(r)
                  // Apply initial prompt when prompt component mounts (e.g., from fork)
                  if (route.initialPrompt) {
                    r.set(route.initialPrompt)
                  }
                }}
                disabled={permissions().length > 0 || questions().length > 0}
                onSubmit={() => {
                  toBottom()
                }}
                sessionID={route.sessionID}
              />
            </box>
          </Show>
          <Toast />
        </box>
        <Show when={sidebarVisible()}>
          <Switch>
            <Match when={wide()}>
              <Sidebar sessionID={route.sessionID} />
            </Match>
            <Match when={!wide()}>
              <box
                position="absolute"
                top={0}
                left={0}
                right={0}
                bottom={0}
                alignItems="flex-end"
                backgroundColor={RGBA.fromInts(0, 0, 0, 70)}
              >
                <Sidebar sessionID={route.sessionID} />
              </box>
            </Match>
          </Switch>
        </Show>
      </box>
    </context.Provider>
  )
}

const MIME_BADGE: Record<string, string> = {
  "text/plain": "txt",
  "image/png": "img",
  "image/jpeg": "img",
  "image/gif": "img",
  "image/webp": "img",
  "application/pdf": "pdf",
  "application/x-directory": "dir",
}

function UserMessage(props: {
  message: UserMessage
  parts: Part[]
  onMouseUp: () => void
  index: number
  pending?: string
}) {
  const ctx = use()
  const local = useLocal()
  const text = createMemo(() => props.parts.flatMap((x) => (x.type === "text" && !x.synthetic ? [x] : []))[0])
  const files = createMemo(() => props.parts.flatMap((x) => (x.type === "file" ? [x] : [])))
  const sync = useSync()
  const { theme } = useTheme()
  const [hover, setHover] = createSignal(false)
  const queued = createMemo(() => props.pending && props.message.id > props.pending)
  const color = createMemo(() => local.agent.color(props.message.agent))
  const queuedFg = createMemo(() => selectedForeground(theme, color()))
  const metadataVisible = createMemo(() => queued() || ctx.showTimestamps())

  const compaction = createMemo(() => props.parts.find((x) => x.type === "compaction"))

  return (
    <>
      <Show when={text()}>
        <box
          id={props.message.id}
          border={["left"]}
          borderColor={color()}
          customBorderChars={SplitBorder.customBorderChars}
          marginTop={props.index === 0 ? 0 : 1}
        >
          <box
            onMouseOver={() => {
              setHover(true)
            }}
            onMouseOut={() => {
              setHover(false)
            }}
            onMouseUp={props.onMouseUp}
            paddingTop={1}
            paddingBottom={1}
            paddingLeft={2}
            backgroundColor={hover() ? theme.backgroundElement : theme.backgroundPanel}
            flexShrink={0}
          >
            <text fg={theme.text}>{text()?.text}</text>
            <Show when={files().length}>
              <box flexDirection="row" paddingBottom={metadataVisible() ? 1 : 0} paddingTop={1} gap={1} flexWrap="wrap">
                <For each={files()}>
                  {(file) => {
                    const bg = createMemo(() => {
                      if (file.mime.startsWith("image/")) return theme.accent
                      if (file.mime === "application/pdf") return theme.primary
                      return theme.secondary
                    })
                    return (
                      <text fg={theme.text}>
                        <span style={{ bg: bg(), fg: theme.background }}> {MIME_BADGE[file.mime] ?? file.mime} </span>
                        <span style={{ bg: theme.backgroundElement, fg: theme.textMuted }}> {file.filename} </span>
                      </text>
                    )
                  }}
                </For>
              </box>
            </Show>
            <Show
              when={queued()}
              fallback={
                <Show when={ctx.showTimestamps()}>
                  <text fg={theme.textMuted}>
                    <span style={{ fg: theme.textMuted }}>
                      {Locale.todayTimeOrDateTime(props.message.time.created)}
                    </span>
                  </text>
                </Show>
              }
            >
              <text fg={theme.textMuted}>
                <span style={{ bg: color(), fg: queuedFg(), bold: true }}> QUEUED </span>
              </text>
            </Show>
          </box>
        </box>
      </Show>
      <Show when={compaction()}>
        <box
          marginTop={1}
          border={["top"]}
          title=" Compaction "
          titleAlignment="center"
          borderColor={theme.borderActive}
        />
      </Show>
    </>
  )
}

function AssistantMessage(props: { message: AssistantMessage; parts: Part[]; last: boolean }) {
  const local = useLocal()
  const { theme } = useTheme()
  const sync = useSync()
  const messages = createMemo(() => sync.data.message[props.message.sessionID] ?? [])

  const final = createMemo(() => {
    return props.message.finish && !["tool-calls", "unknown"].includes(props.message.finish)
  })

  const duration = createMemo(() => {
    if (!final()) return 0
    if (!props.message.time.completed) return 0
    const user = messages().find((x) => x.role === "user" && x.id === props.message.parentID)
    if (!user || !user.time) return 0
    return props.message.time.completed - user.time.created
  })

  const keybind = useKeybind()

  return (
    <>
      <For each={props.parts}>
        {(part, index) => {
          const component = createMemo(() => PART_MAPPING[part.type as keyof typeof PART_MAPPING])
          return (
            <Show when={component()}>
              <Dynamic
                last={index() === props.parts.length - 1}
                component={component()}
                part={part as any}
                message={props.message}
              />
            </Show>
          )
        }}
      </For>
      <Show when={props.parts.some((x) => x.type === "tool" && x.tool === "task")}>
        <box paddingTop={1} paddingLeft={3}>
          <text fg={theme.text}>
            {keybind.print("session_child_first")}
            <span style={{ fg: theme.textMuted }}> view subagents</span>
          </text>
        </box>
      </Show>
      <Show when={props.message.error && props.message.error.name !== "MessageAbortedError"}>
        <box
          border={["left"]}
          paddingTop={1}
          paddingBottom={1}
          paddingLeft={2}
          marginTop={1}
          backgroundColor={theme.backgroundPanel}
          customBorderChars={SplitBorder.customBorderChars}
          borderColor={theme.error}
        >
          <text fg={theme.textMuted}>{props.message.error?.data.message}</text>
        </box>
      </Show>
      <Switch>
        <Match when={props.last || final() || props.message.error?.name === "MessageAbortedError"}>
          <box paddingLeft={3}>
            <text marginTop={1}>
              <span
                style={{
                  fg:
                    props.message.error?.name === "MessageAbortedError"
                      ? theme.textMuted
                      : local.agent.color(props.message.agent),
                }}
              >
                ▣{" "}
              </span>{" "}
              <span style={{ fg: theme.text }}>{Locale.titlecase(props.message.mode)}</span>
              <span style={{ fg: theme.textMuted }}> · {props.message.modelID}</span>
              <Show when={duration()}>
                <span style={{ fg: theme.textMuted }}> · {Locale.duration(duration())}</span>
              </Show>
              <Show when={props.message.error?.name === "MessageAbortedError"}>
                <span style={{ fg: theme.textMuted }}> · interrupted</span>
              </Show>
            </text>
          </box>
        </Match>
      </Switch>
    </>
  )
}

const PART_MAPPING = {
  text: TextPart,
  tool: ToolPart,
  reasoning: ReasoningPart,
}

function ReasoningPart(props: { last: boolean; part: ReasoningPart; message: AssistantMessage }) {
  const { theme, subtleSyntax } = useTheme()
  const ctx = use()
  const content = createMemo(() => {
    // Filter out redacted reasoning chunks from OpenRouter
    // OpenRouter sends encrypted reasoning data that appears as [REDACTED]
    return props.part.text.replace("[REDACTED]", "").trim()
  })
  return (
    <Show when={content() && ctx.showThinking()}>
      <box
        id={"text-" + props.part.id}
        paddingLeft={2}
        marginTop={1}
        flexDirection="column"
        border={["left"]}
        customBorderChars={SplitBorder.customBorderChars}
        borderColor={theme.backgroundElement}
      >
        <code
          filetype="markdown"
          drawUnstyledText={false}
          streaming={true}
          syntaxStyle={subtleSyntax()}
          content={"_Thinking:_ " + content()}
          conceal={ctx.conceal()}
          fg={theme.textMuted}
        />
      </box>
    </Show>
  )
}

function TextPart(props: { last: boolean; part: TextPart; message: AssistantMessage }) {
  const ctx = use()
  const { theme, syntax } = useTheme()
  return (
    <Show when={props.part.text.trim()}>
      <box id={"text-" + props.part.id} paddingLeft={3} marginTop={1} flexShrink={0}>
        <Switch>
          <Match when={Flag.MALIBU_EXPERIMENTAL_MARKDOWN}>
            <markdown
              syntaxStyle={syntax()}
              streaming={true}
              content={props.part.text.trim()}
              conceal={ctx.conceal()}
            />
          </Match>
          <Match when={!Flag.MALIBU_EXPERIMENTAL_MARKDOWN}>
            <code
              filetype="markdown"
              drawUnstyledText={false}
              streaming={true}
              syntaxStyle={syntax()}
              content={props.part.text.trim()}
              conceal={ctx.conceal()}
              fg={theme.text}
            />
          </Match>
        </Switch>
      </box>
    </Show>
  )
}

// Pending messages moved to individual tool pending functions

function ToolPart(props: { last: boolean; part: ToolPart; message: AssistantMessage }) {
  const ctx = use()
  const sync = useSync()

  // Hide tool if showDetails is false and tool completed successfully
  const shouldHide = createMemo(() => {
    if (ctx.showDetails()) return false
    if (props.part.state.status !== "completed") return false
    return true
  })

  const toolprops = {
    get metadata() {
      return props.part.state.status === "pending" ? {} : (props.part.state.metadata ?? {})
    },
    get input() {
      return props.part.state.input ?? {}
    },
    get output() {
      return props.part.state.status === "completed" ? props.part.state.output : undefined
    },
    get permission() {
      const permissions = sync.data.permission[props.message.sessionID] ?? []
      const permissionIndex = permissions.findIndex((x) => x.tool?.callID === props.part.callID)
      return permissions[permissionIndex]
    },
    get tool() {
      return props.part.tool
    },
    get part() {
      return props.part
    },
  }

  return (
    <Show when={!shouldHide()}>
      <Switch>
        <Match when={props.part.tool === "bash"}>
          <Bash {...toolprops} />
        </Match>
        <Match when={props.part.tool === "glob"}>
          <Glob {...toolprops} />
        </Match>
        <Match when={props.part.tool === "read"}>
          <Read {...toolprops} />
        </Match>
        <Match when={props.part.tool === "grep"}>
          <Grep {...toolprops} />
        </Match>
        <Match when={props.part.tool === "list"}>
          <List {...toolprops} />
        </Match>
        <Match when={props.part.tool === "webfetch"}>
          <WebFetch {...toolprops} />
        </Match>
        <Match when={props.part.tool === "codesearch"}>
          <CodeSearch {...toolprops} />
        </Match>
        <Match when={props.part.tool === "websearch"}>
          <WebSearch {...toolprops} />
        </Match>
        <Match when={props.part.tool === "write"}>
          <Write {...toolprops} />
        </Match>
        <Match when={props.part.tool === "edit"}>
          <Edit {...toolprops} />
        </Match>
        <Match when={props.part.tool === "task"}>
          <Task {...toolprops} />
        </Match>
        <Match when={props.part.tool === "apply_patch"}>
          <ApplyPatch {...toolprops} />
        </Match>
        <Match when={props.part.tool === "todowrite"}>
          <TodoWrite {...toolprops} />
        </Match>
        <Match when={props.part.tool === "todoread"}>
          <TodoRead {...toolprops} />
        </Match>
        <Match when={props.part.tool === "question"}>
          <Question {...toolprops} />
        </Match>
        <Match when={props.part.tool === "skill"}>
          <Skill {...toolprops} />
        </Match>
        <Match when={props.part.tool === "read_file"}>
          <Read {...toolprops} />
        </Match>
        <Match when={props.part.tool === "write_file"}>
          <Write {...toolprops} />
        </Match>
        <Match when={props.part.tool === "edit_file"}>
          <Edit {...toolprops} />
        </Match>
        <Match when={props.part.tool === "ls"}>
          <List {...toolprops} />
        </Match>
        <Match when={props.part.tool === "write_todos"}>
          <TodoWrite {...toolprops} />
        </Match>
        <Match when={props.part.tool === "background_task"}>
          <BackgroundTask {...toolprops} />
        </Match>
        <Match when={props.part.tool === "task_progress"}>
          <TaskProgress {...toolprops} />
        </Match>
        <Match when={props.part.tool === "wait_background_task"}>
          <WaitBackgroundTask {...toolprops} />
        </Match>
        <Match when={props.part.tool === "cancel_background_task"}>
          <CancelBackgroundTask {...toolprops} />
        </Match>
        <Match when={props.part.tool === "multiedit"}>
          <MultiEdit {...toolprops} />
        </Match>
        <Match when={props.part.tool === "plan_exit"}>
          <PlanExit {...toolprops} />
        </Match>
        <Match when={props.part.tool === "invalid"}>
          <Invalid {...toolprops} />
        </Match>
        <Match when={props.part.tool === "batch"}>
          <BatchTool {...toolprops} />
        </Match>
        <Match when={props.part.tool === "lsp"}>
          <LspTool {...toolprops} />
        </Match>
        <Match when={true}>
          <GenericTool {...toolprops} />
        </Match>
      </Switch>
    </Show>
  )
}

type ToolProps<T extends Tool.Info> = {
  input: Partial<Tool.InferParameters<T>>
  metadata: Partial<Tool.InferMetadata<T>>
  permission: Record<string, any>
  tool: string
  output?: string
  part: ToolPart
}
function GenericTool(props: ToolProps<any>) {
  const { theme } = useTheme()
  const ctx = use()
  const output = createMemo(() => props.output?.trim() ?? "")
  const [expanded, setExpanded] = createSignal(false)
  const lines = createMemo(() => output().split("\n"))
  const maxLines = 3
  const overflow = createMemo(() => lines().length > maxLines)
  const limited = createMemo(() => {
    if (expanded() || !overflow()) return output()
    return [...lines().slice(0, maxLines), "…"].join("\n")
  })
  const display = createMemo(() => formatToolCall(props.tool, props.input))

  return (
    <Show
      when={props.output && ctx.showGenericToolOutput()}
      fallback={
        <InlineTool icon="⚙" pending="Running..." complete={true} part={props.part}>
          {display()}
        </InlineTool>
      }
    >
      <BlockTool
        title={display()}
        part={props.part}
        onClick={overflow() ? () => setExpanded((prev) => !prev) : undefined}
      >
        <box gap={1}>
          <text fg={theme.text}>{limited()}</text>
          <Show when={overflow()}>
            <text fg={theme.textMuted}>{expanded() ? "Click to collapse" : "Click to expand"}</text>
          </Show>
        </box>
      </BlockTool>
    </Show>
  )
}

function ToolTitle(props: { fallback: string; when: any; icon: string; children: JSX.Element }) {
  const { theme } = useTheme()
  return (
    <text paddingLeft={3} fg={props.when ? theme.textMuted : theme.text}>
      <Show fallback={<>~ {props.fallback}</>} when={props.when}>
        <span style={{ bold: true }}>{props.icon}</span> {props.children}
      </Show>
    </text>
  )
}

function InlineTool(props: {
  icon: string
  iconColor?: RGBA
  complete: any
  pending: string
  spinner?: boolean
  children: JSX.Element
  part: ToolPart
  onClick?: () => void
  outputPreview?: string
}) {
  const [margin, setMargin] = createSignal(0)
  const { theme } = useTheme()
  const ctx = use()
  const sync = useSync()
  const renderer = useRenderer()
  const [hover, setHover] = createSignal(false)

  const permission = createMemo(() => {
    const callID = sync.data.permission[ctx.sessionID]?.at(0)?.tool?.callID
    if (!callID) return false
    return callID === props.part.callID
  })

  const fg = createMemo(() => {
    if (permission()) return theme.warning
    if (hover() && props.onClick) return theme.text
    if (props.complete) return theme.textMuted
    return theme.text
  })

  const error = createMemo(() => (props.part.state.status === "error" ? props.part.state.error : undefined))

  const denied = createMemo(
    () =>
      error()?.includes("QuestionRejectedError") ||
      error()?.includes("rejected permission") ||
      error()?.includes("specified a rule") ||
      error()?.includes("user dismissed"),
  )

  return (
    <box
      marginTop={margin()}
      paddingLeft={3}
      onMouseOver={() => props.onClick && setHover(true)}
      onMouseOut={() => setHover(false)}
      onMouseUp={() => {
        if (renderer.getSelection()?.getSelectedText()) return
        props.onClick?.()
      }}
      renderBefore={function () {
        const el = this as BoxRenderable
        const parent = el.parent
        if (!parent) {
          return
        }
        if (el.height > 1) {
          setMargin(1)
          return
        }
        const children = parent.getChildren()
        const index = children.indexOf(el)
        const previous = children[index - 1]
        if (!previous) {
          setMargin(0)
          return
        }
        if (previous.height > 1 || previous.id.startsWith("text-")) {
          setMargin(1)
          return
        }
      }}
    >
      <Switch>
        <Match when={props.spinner}>
          <Spinner color={fg()} children={props.children} />
        </Match>
        <Match when={true}>
          <text paddingLeft={3} fg={fg()} attributes={denied() ? TextAttributes.STRIKETHROUGH : undefined}>
            <Show
              fallback={<>~ {props.complete ? props.children : props.pending}</>}
              when={props.part.state.status === "completed" || props.part.state.status === "error"}
            >
              <span style={{ fg: props.iconColor }}>{props.icon}</span> {props.children}
            </Show>
          </text>
        </Match>
      </Switch>
      <Show when={props.outputPreview && (props.part.state.status === "completed" || props.part.state.status === "error")}>
        <text paddingLeft={6} fg={theme.textMuted}>
          ⎿  {props.outputPreview}
        </text>
      </Show>
      <Show when={error() && !denied()}>
        <text fg={theme.error}>{error()}</text>
      </Show>
    </box>
  )
}

function BlockTool(props: {
  title: string
  children: JSX.Element
  onClick?: () => void
  part?: ToolPart
  spinner?: boolean
}) {
  const { theme } = useTheme()
  const renderer = useRenderer()
  const [hover, setHover] = createSignal(false)
  const error = createMemo(() => (props.part?.state.status === "error" ? props.part.state.error : undefined))
  return (
    <box
      border={["left"]}
      paddingTop={1}
      paddingBottom={1}
      paddingLeft={2}
      marginTop={1}
      gap={1}
      backgroundColor={hover() ? theme.backgroundMenu : theme.backgroundPanel}
      customBorderChars={SplitBorder.customBorderChars}
      borderColor={theme.background}
      onMouseOver={() => props.onClick && setHover(true)}
      onMouseOut={() => setHover(false)}
      onMouseUp={() => {
        if (renderer.getSelection()?.getSelectedText()) return
        props.onClick?.()
      }}
    >
      <Show
        when={props.spinner}
        fallback={
          <text paddingLeft={3} fg={theme.textMuted}>
            {props.title}
          </text>
        }
      >
        <Spinner color={theme.textMuted}>{props.title.replace(/^# /, "")}</Spinner>
      </Show>
      {props.children}
      <Show when={error()}>
        <text fg={theme.error}>{error()}</text>
      </Show>
    </box>
  )
}

function ToolOutputPreview(props: {
  output: string
  maxLines?: number
  language?: string
  maxChars?: number
}) {
  const { theme, syntax } = useTheme()
  const renderer = useRenderer()
  const maxLines = props.maxLines ?? 8
  const maxExpandedLines = maxLines * 4
  const maxChars = props.maxChars ?? 20000

  // Pre-slice large outputs for performance, trim to last complete line
  const sliced = createMemo(() => {
    const raw = props.output
    if (!raw || !raw.trim()) return ""
    if (raw.length <= maxChars) return raw
    const cut = raw.slice(0, maxChars)
    const lastNewline = cut.lastIndexOf("\n")
    return lastNewline > 0 ? cut.slice(0, lastNewline) : cut
  })

  const lines = createMemo(() => sliced().split("\n"))
  const overflow = createMemo(() => lines().length > maxLines)
  const [expanded, setExpanded] = createSignal(false)

  // Reset expanded state when output changes
  createEffect(() => {
    props.output // track dependency
    setExpanded(false)
  })

  const limited = createMemo(() => {
    if (!overflow()) return sliced()
    if (expanded()) return lines().slice(0, maxExpandedLines).join("\n")
    return lines().slice(0, maxLines).join("\n")
  })

  const hiddenCount = createMemo(() => {
    if (!overflow()) return 0
    if (expanded()) return Math.max(0, lines().length - maxExpandedLines)
    return lines().length - maxLines
  })

  return (
    <Show when={sliced()}>
      <box
        gap={1}
        onMouseUp={() => {
          if (renderer.getSelection()?.getSelectedText()) return
          if (overflow()) setExpanded((prev) => !prev)
        }}
      >
        <Show
          when={props.language}
          fallback={<text fg={theme.text}>{limited()}</text>}
        >
          <code filetype={props.language} syntaxStyle={syntax()} content={limited()} fg={theme.text} />
        </Show>
        <Show when={overflow()}>
          <text fg={theme.textMuted}>
            {expanded()
              ? hiddenCount() > 0
                ? `▴ ${hiddenCount()} more lines hidden`
                : "▴ Click to collapse"
              : `▾ ${hiddenCount()} more lines…`}
          </text>
        </Show>
      </box>
    </Show>
  )
}

function Bash(props: ToolProps<typeof BashTool>) {
  const { theme } = useTheme()
  const sync = useSync()
  const isRunning = createMemo(() => props.part.state.status === "running")
  const output = createMemo(() => stripAnsi(props.metadata.output?.trim() ?? ""))
  const [expanded, setExpanded] = createSignal(false)
  const lines = createMemo(() => output().split("\n"))
  const overflow = createMemo(() => lines().length > 3)
  const limited = createMemo(() => {
    if (expanded() || !overflow()) return output()
    return [...lines().slice(0, 3), "…"].join("\n")
  })

  const cmdDisplay = createMemo(() => {
    const cmd = props.input.command
    if (!cmd) return "Bash()"
    // Truncate very long commands for display
    const maxLen = 200
    const truncated = cmd.length > maxLen ? cmd.slice(0, maxLen) + "..." : cmd
    return `Bash(${truncated})`
  })

  const workdirDisplay = createMemo(() => {
    const workdir = props.input.workdir
    if (!workdir || workdir === ".") return undefined

    const base = sync.data.path.directory
    if (!base) return undefined

    const absolute = path.resolve(base, workdir)
    if (absolute === base) return undefined

    const home = Global.Path.home
    if (!home) return absolute

    const match = absolute === home || absolute.startsWith(home + path.sep)
    return match ? absolute.replace(home, "~") : absolute
  })

  const title = createMemo(() => {
    const desc = props.input.description ?? cmdDisplay()
    const wd = workdirDisplay()
    if (!wd) return desc
    if (desc.includes(wd)) return desc
    return `${desc} in ${wd}`
  })

  return (
    <Switch>
      <Match when={props.metadata.output !== undefined}>
        <BlockTool
          title={title()}
          part={props.part}
          spinner={isRunning()}
          onClick={overflow() ? () => setExpanded((prev) => !prev) : undefined}
        >
          <box gap={1}>
            <text fg={theme.textMuted}>⎿  $ {props.input.command}</text>
            <Show when={output()}>
              <text fg={theme.text}>{limited()}</text>
            </Show>
            <Show when={overflow()}>
              <text fg={theme.textMuted}>{expanded() ? "Click to collapse" : "Click to expand"}</text>
            </Show>
          </box>
        </BlockTool>
      </Match>
      <Match when={true}>
        <InlineTool icon="●" pending="Running command..." complete={props.input.command} part={props.part}>
          {cmdDisplay()}
        </InlineTool>
      </Match>
    </Switch>
  )
}

function Write(props: ToolProps<typeof WriteTool>) {
  const { theme, syntax } = useTheme()
  const fp = () => (props.input as any).filePath ?? (props.input as any).file_path
  const code = createMemo(() => {
    if (!props.input.content) return ""
    return props.input.content
  })
  const display = createMemo(() => {
    const filePath = fp()
    if (!filePath) return "Write()"
    return `Write(${normalizePath(filePath)})`
  })
  const lineCount = createMemo(() => {
    if (!code()) return undefined
    const count = code().split("\n").length
    return `${count} line${count !== 1 ? "s" : ""}`
  })

  return (
    <Switch>
      <Match when={props.metadata.diagnostics !== undefined}>
        <BlockTool title={display()} part={props.part}>
          <line_number fg={theme.textMuted} minWidth={3} paddingRight={1}>
            <code
              conceal={false}
              fg={theme.text}
              filetype={filetype(fp()!)}
              syntaxStyle={syntax()}
              content={code()}
            />
          </line_number>
          <Diagnostics diagnostics={props.metadata.diagnostics} filePath={fp() ?? ""} />
        </BlockTool>
      </Match>
      <Match when={props.part.state.status === "completed" && code()}>
        <BlockTool title={display()} part={props.part}>
          <ToolOutputPreview output={code()} maxLines={10} language={filetype(fp()!)} />
        </BlockTool>
      </Match>
      <Match when={true}>
        <InlineTool icon="←" pending="Preparing write..." complete={fp()} part={props.part} outputPreview={lineCount()}>
          {display()}
        </InlineTool>
      </Match>
    </Switch>
  )
}

function Glob(props: ToolProps<typeof GlobTool>) {
  const { theme } = useTheme()
  const compacted = createMemo(
    () => props.part.state.status === "completed" && (props.part.state as any).time?.compacted,
  )
  const display = createMemo(() => formatToolCall("Glob", props.input, "pattern"))
  const matchSummary = createMemo(() => {
    const count = props.metadata.count
    if (!count) return undefined
    return `${count} ${count === 1 ? "match" : "matches"}`
  })
  return (
    <Switch>
      <Match when={props.output?.trim() && (props.metadata.count ?? 0) > 0 && !compacted()}>
        <BlockTool
          title={display()}
          part={props.part}
        >
          <Show when={matchSummary()}>
            <text fg={theme.textMuted}>⎿  {matchSummary()}</text>
          </Show>
          <ToolOutputPreview output={props.output!} maxLines={3} />
        </BlockTool>
      </Match>
      <Match when={true}>
        <InlineTool
          icon="✱"
          pending="Finding files..."
          complete={props.input.pattern}
          part={props.part}
          outputPreview={matchSummary()}
        >
          {display()}
        </InlineTool>
      </Match>
    </Switch>
  )
}

function Read(props: ToolProps<typeof ReadTool>) {
  const { theme } = useTheme()
  const fp = () => (props.input as any).filePath ?? (props.input as any).file_path
  const isRunning = createMemo(() => props.part.state.status === "running")
  const loaded = createMemo(() => {
    if (props.part.state.status !== "completed") return []
    if (props.part.state.time.compacted) return []
    const value = props.metadata.loaded
    if (!value || !Array.isArray(value)) return []
    return value.filter((p): p is string => typeof p === "string")
  })
  const display = createMemo(() => {
    const filePath = fp()
    if (!filePath) return "Read()"
    const normalized = normalizePath(filePath)
    const extra = input(props.input, ["filePath", "file_path"])
    return extra ? `Read(${JSON.stringify(normalized)}) ${extra}` : `Read(${JSON.stringify(normalized)})`
  })
  return (
    <>
      <InlineTool
        icon="→"
        pending="Reading file..."
        complete={fp()}
        spinner={isRunning()}
        part={props.part}
      >
        {display()}
      </InlineTool>
      <For each={loaded()}>
        {(filepath) => (
          <box paddingLeft={3}>
            <text paddingLeft={3} fg={theme.textMuted}>
              ⎿  Loaded {normalizePath(filepath)}
            </text>
          </box>
        )}
      </For>
    </>
  )
}

function Grep(props: ToolProps<typeof GrepTool>) {
  const { theme } = useTheme()
  const compacted = createMemo(
    () => props.part.state.status === "completed" && (props.part.state as any).time?.compacted,
  )
  const display = createMemo(() => formatToolCall("Grep", props.input, "pattern"))
  const matchSummary = createMemo(() => {
    const count = props.metadata.matches
    if (!count) return undefined
    return `${count} ${count === 1 ? "match" : "matches"}`
  })
  return (
    <Switch>
      <Match when={props.output && (props.metadata.matches ?? 0) > 0 && !compacted()}>
        <BlockTool
          title={display()}
          part={props.part}
        >
          <Show when={matchSummary()}>
            <text fg={theme.textMuted}>⎿  {matchSummary()}</text>
          </Show>
          <ToolOutputPreview output={props.output!} maxLines={3} />
        </BlockTool>
      </Match>
      <Match when={true}>
        <InlineTool
          icon="✱"
          pending="Searching content..."
          complete={props.input.pattern}
          part={props.part}
          outputPreview={matchSummary()}
        >
          {display()}
        </InlineTool>
      </Match>
    </Switch>
  )
}

function List(props: ToolProps<typeof ListTool>) {
  const display = createMemo(() => {
    const p = props.input.path
    if (p) return `List(${JSON.stringify(normalizePath(p))})`
    return "List()"
  })
  return (
    <InlineTool icon="→" pending="Listing directory..." complete={props.input.path !== undefined} part={props.part}>
      {display()}
    </InlineTool>
  )
}

function WebFetch(props: ToolProps<typeof WebFetchTool>) {
  const url = () => (props.input as any).url
  const compacted = createMemo(
    () => props.part.state.status === "completed" && (props.part.state as any).time?.compacted,
  )
  const display = createMemo(() => {
    const u = url()
    return u ? `WebFetch(${JSON.stringify(u)})` : "WebFetch()"
  })
  return (
    <Switch>
      <Match when={props.output && props.output.trim() && !compacted()}>
        <BlockTool title={display()} part={props.part}>
          <ToolOutputPreview output={props.output!} maxLines={3} language="markdown" />
        </BlockTool>
      </Match>
      <Match when={true}>
        <InlineTool icon="%" pending="Fetching from the web..." complete={url()} part={props.part}>
          {display()}
        </InlineTool>
      </Match>
    </Switch>
  )
}

function CodeSearch(props: ToolProps<any>) {
  const { theme } = useTheme()
  const inp = props.input as any
  const metadata = props.metadata as any
  const compacted = createMemo(
    () => props.part.state.status === "completed" && (props.part.state as any).time?.compacted,
  )
  const display = createMemo(() => inp.query ? `CodeSearch(${JSON.stringify(inp.query)})` : "CodeSearch()")
  const resultSummary = createMemo(() => metadata.results ? `${metadata.results} results` : undefined)
  return (
    <Switch>
      <Match when={props.output && props.output.trim() && !compacted()}>
        <BlockTool title={display()} part={props.part}>
          <Show when={resultSummary()}>
            <text fg={theme.textMuted}>⎿  {resultSummary()}</text>
          </Show>
          <ToolOutputPreview output={props.output!} maxLines={3} />
        </BlockTool>
      </Match>
      <Match when={true}>
        <InlineTool icon="◇" pending="Searching code..." complete={inp.query} part={props.part} outputPreview={resultSummary()}>
          {display()}
        </InlineTool>
      </Match>
    </Switch>
  )
}

function WebSearch(props: ToolProps<any>) {
  const { theme } = useTheme()
  const inp = props.input as any
  const metadata = props.metadata as any
  const compacted = createMemo(
    () => props.part.state.status === "completed" && (props.part.state as any).time?.compacted,
  )
  const display = createMemo(() => inp.query ? `WebSearch(${JSON.stringify(inp.query)})` : "WebSearch()")
  const resultSummary = createMemo(() => metadata.numResults ? `${metadata.numResults} results` : undefined)
  return (
    <Switch>
      <Match when={props.output && props.output.trim() && !compacted()}>
        <BlockTool title={display()} part={props.part}>
          <Show when={resultSummary()}>
            <text fg={theme.textMuted}>⎿  {resultSummary()}</text>
          </Show>
          <ToolOutputPreview output={props.output!} maxLines={3} />
        </BlockTool>
      </Match>
      <Match when={true}>
        <InlineTool icon="◈" pending="Searching web..." complete={inp.query} part={props.part} outputPreview={resultSummary()}>
          {display()}
        </InlineTool>
      </Match>
    </Switch>
  )
}

function Task(props: ToolProps<typeof TaskTool>) {
  const { theme } = useTheme()
  const keybind = useKeybind()
  const { navigate } = useRoute()
  const local = useLocal()
  const sync = useSync()

  onMount(() => {
    if (props.metadata.sessionId && !sync.data.message[props.metadata.sessionId]?.length)
      sync.session.sync(props.metadata.sessionId)
  })

  const messages = createMemo(() => sync.data.message[props.metadata.sessionId ?? ""] ?? [])

  const tools = createMemo(() => {
    return messages().flatMap((msg) =>
      (sync.data.part[msg.id] ?? [])
        .filter((part): part is ToolPart => part.type === "tool")
        .map((part) => ({ tool: part.tool, state: part.state })),
    )
  })

  const current = createMemo(() => tools().findLast((x) => (x.state as any).title))

  const isRunning = createMemo(() => props.part.state.status === "running")

  const duration = createMemo(() => {
    const first = messages().find((x) => x.role === "user")?.time.created
    const assistant = messages().findLast((x) => x.role === "assistant")?.time.completed
    if (!first || !assistant) return 0
    return assistant - first
  })

  const agentType = createMemo(() => {
    const type = props.input.subagent_type
    if (!type) return "Task"
    return Locale.titlecase(type)
  })

  const content = createMemo(() => {
    if (!props.input.description) return ""
    let content = [`${agentType()} ${props.input.description}`]

    if (isRunning() && tools().length > 0) {
      if (current()) content.push(`↳ ${Locale.titlecase(current()!.tool)} ${(current()!.state as any).title}`)
      else content.push(`↳ ${tools().length} tool uses`)
    }

    if (props.part.state.status === "completed") {
      content.push(`└ ${tools().length} tool uses · ${Locale.duration(duration())}`)
    }

    return content.join("\n")
  })

  return (
    <InlineTool
      icon="│"
      spinner={isRunning()}
      complete={props.input.description}
      pending={`Launching ${agentType().toLowerCase()} agent...`}
      part={props.part}
      onClick={() => {
        if (props.metadata.sessionId) {
          navigate({ type: "session", sessionID: props.metadata.sessionId })
        }
      }}
    >
      {content()}
    </InlineTool>
  )
}

interface BackgroundTaskInfo {
  taskId: string
  taskNumber: number
  agentName: string
  description: string
  status: string
  toolCount?: number
  tokenUsage?: number
}

function formatTokens(tokens?: number): string {
  if (!tokens) return "0"
  return (tokens / 1000).toFixed(1) + "k"
}

function BackgroundTaskGroup(props: { tasks: BackgroundTaskInfo[] }) {
  const { theme } = useTheme()

  const tasks = createMemo(() => props.tasks ?? [])
  const total = createMemo(() => tasks().length)

  const headerText = createMemo(() => {
    const t = tasks()
    if (t.length === 0) return "No background tasks"
    const finished = t.filter((x) => x.status !== "running").length
    const counts = new Map<string, number>()
    for (const x of t) {
      counts.set(x.agentName, (counts.get(x.agentName) || 0) + 1)
    }
    const agentParts: string[] = []
    for (const [name, count] of counts) {
      agentParts.push(`${count} ${Locale.titlecase(name)}`)
    }
    const agentStr = agentParts.join(" + ")
    if (finished === t.length) return `${agentStr} agent${t.length !== 1 ? "s" : ""} finished`
    return `${agentStr} agent${t.length !== 1 ? "s" : ""} (${finished}/${t.length} finished)`
  })

  const allDone = createMemo(() => tasks().length > 0 && tasks().every((t) => t.status !== "running"))

  return (
    <box flexDirection="column" paddingLeft={3}>
      <text fg={allDone() ? theme.text : theme.warning}>
        <span style={{ bold: true }}>{allDone() ? "●" : "○"}</span> {headerText()}
      </text>
      <For each={tasks()}>
        {(task, i) => {
          const isLast = createMemo(() => i() === total() - 1)
          const prefix = createMemo(() => (isLast() ? "└─" : "├─"))
          const subPrefix = createMemo(() => (isLast() ? "   " : "│  "))

          const statusColor = () => {
            switch (task.status) {
              case "success":
                return theme.text
              case "error":
                return theme.error
              case "cancelled":
              case "timeout":
                return theme.textMuted
              default:
                return theme.warning
            }
          }

          const statusText = () => {
            switch (task.status) {
              case "success":
                return "Done"
              case "error":
                return "Error"
              case "cancelled":
                return "Cancelled"
              case "timeout":
                return "Timed out"
              default:
                return "Running..."
            }
          }

          const metricsStr = createMemo(() => {
            const parts: string[] = []
            if (task.toolCount != null && task.toolCount > 0) parts.push(`${task.toolCount} tool uses`)
            if (task.tokenUsage != null && task.tokenUsage > 0) parts.push(`${formatTokens(task.tokenUsage)} tokens`)
            return parts.length > 0 ? " · " + parts.join(" · ") : ""
          })

          return (
            <box flexDirection="column">
              <text fg={theme.textMuted}>
                {"   "}{prefix()} {Locale.titlecase(task.agentName)} {task.description}{metricsStr()}
              </text>
              <text fg={statusColor()}>
                {"   "}{subPrefix()} ⎿  {statusText()}
              </text>
            </box>
          )
        }}
      </For>
    </box>
  )
}

function BackgroundTask(props: ToolProps<any>) {
  const inp = props.input as any
  const agentType = () => inp.subagent_type ?? "agent"
  const desc = () => inp.description ?? ""
  const taskNum = createMemo(() => {
    const output = props.output ?? ""
    const match = output.match(/Task-(\d+)/)
    return match ? match[1] : ""
  })

  return (
    <InlineTool
      icon="●"
      spinner={props.part.state.status === "running"}
      pending={`Launching ${agentType()} agent...`}
      complete={taskNum() ? `Task-${taskNum()}` : true}
      part={props.part}
      outputPreview={`${Locale.titlecase(agentType())} · ${desc().slice(0, 60)}${desc().length > 60 ? "..." : ""}`}
    >
      {`BackgroundTask(${JSON.stringify(agentType())})`}
    </InlineTool>
  )
}

function TaskProgress(props: ToolProps<any>) {
  const inp = props.input as any
  const taskNum = () => inp.task_number ?? "?"

  const statusPreview = createMemo(() => {
    const output = props.output ?? ""
    if (output.includes("**completed**")) return "Completed"
    if (output.includes("**running**")) return "Running"
    if (output.includes("**error**")) return "Error"
    if (output.includes("**cancelled**")) return "Cancelled"
    return undefined
  })

  return (
    <InlineTool
      icon="◎"
      spinner={props.part.state.status === "running"}
      pending={`Checking Task-${taskNum()}...`}
      complete={statusPreview() ?? true}
      part={props.part}
      outputPreview={statusPreview()}
    >
      {`TaskProgress(Task-${taskNum()})`}
    </InlineTool>
  )
}

function WaitBackgroundTask(props: ToolProps<any>) {
  const inp = props.input as any
  const taskNum = () => inp.task_number
  const isWaitAll = () => taskNum() == null

  // Parse background task records from the embedded JSON in the output
  const richRecords = createMemo((): BackgroundTaskInfo[] => {
    const output = props.output ?? ""
    if (!output) return []

    // Parse embedded JSON metadata: <!-- BACKGROUND_TASKS:[...] -->
    const metaMatch = output.match(/<!-- BACKGROUND_TASKS:(\[[\s\S]*?\]) -->/)
    if (metaMatch) {
      try {
        const parsed = JSON.parse(metaMatch[1]) as any[]
        return parsed.map((record: any) => ({
          taskId: record.taskId ?? "",
          taskNumber: record.taskNumber ?? 0,
          agentName: record.agentName ?? "agent",
          description: record.description ?? "",
          status: record.status ?? "success",
          toolCount: record.toolCount,
          tokenUsage: record.tokenUsage,
        })).sort((a: BackgroundTaskInfo, b: BackgroundTaskInfo) => a.taskNumber - b.taskNumber)
      } catch {
        // Fall through to basic parsing
      }
    }

    // Fallback: parse from ### Task-N: **status** format
    const records: BackgroundTaskInfo[] = []
    const taskBlocks = output.split(/### Task-(\d+):/)
    for (let i = 1; i < taskBlocks.length; i += 2) {
      const num = parseInt(taskBlocks[i], 10)
      const block = taskBlocks[i + 1] ?? ""
      const statusMatch = block.match(/\*\*(\w+)\*\*/)
      const status = statusMatch?.[1] === "completed" ? "success" : statusMatch?.[1] ?? "success"
      records.push({
        taskId: `task-${num}`,
        taskNumber: num,
        agentName: "agent",
        description: `Task-${num}`,
        status,
      })
    }
    return records
  })

  return (
    <Switch>
      <Match when={isWaitAll() && props.part.state.status === "completed" && richRecords().length > 0}>
        <BackgroundTaskGroup tasks={richRecords()} />
      </Match>
      <Match when={true}>
        <InlineTool
          icon="◎"
          spinner={props.part.state.status === "running"}
          pending={isWaitAll() ? "Waiting for all tasks..." : `Waiting for Task-${taskNum()}...`}
          complete={true}
          part={props.part}
        >
          {isWaitAll() ? "WaitBackgroundTask(all)" : `WaitBackgroundTask(Task-${taskNum()})`}
        </InlineTool>
      </Match>
    </Switch>
  )
}

function CancelBackgroundTask(props: ToolProps<any>) {
  const inp = props.input as any
  const taskNum = () => inp.task_number ?? "?"

  return (
    <InlineTool
      icon="⊘"
      spinner={props.part.state.status === "running"}
      pending={`Cancelling Task-${taskNum()}...`}
      complete={`Task-${taskNum()} cancelled`}
      part={props.part}
    >
      {`CancelBackgroundTask(Task-${taskNum()})`}
    </InlineTool>
  )
}

function Edit(props: ToolProps<typeof EditTool>) {
  const ctx = use()
  const { theme, syntax } = useTheme()
  const fp = () => (props.input as any).filePath ?? (props.input as any).file_path
  const replAll = () => (props.input as any).replaceAll ?? (props.input as any).replace_all

  const view = createMemo(() => {
    const diffStyle = ctx.tui.diff_style
    if (diffStyle === "stacked") return "unified"
    return ctx.width > 120 ? "split" : "unified"
  })

  const ft = createMemo(() => filetype(fp()))
  const diffContent = createMemo(() => props.metadata.diff)

  const display = createMemo(() => {
    const filePath = fp()
    if (!filePath) return "Edit()"
    return `Edit(${normalizePath(filePath)})`
  })

  const diffSummary = createMemo(() => {
    const diff = props.metadata.diff
    if (!diff) return undefined
    const lines = (typeof diff === "string" ? diff : "").split("\n")
    let added = 0
    let removed = 0
    for (const line of lines) {
      if (line.startsWith("+") && !line.startsWith("+++")) added++
      else if (line.startsWith("-") && !line.startsWith("---")) removed++
    }
    if (added === 0 && removed === 0) return undefined
    const parts: string[] = []
    if (added > 0) parts.push(`Added ${added} line${added !== 1 ? "s" : ""}`)
    if (removed > 0) parts.push(`removed ${removed} line${removed !== 1 ? "s" : ""}`)
    return parts.join(", ")
  })

  return (
    <Switch>
      <Match when={props.metadata.diff !== undefined}>
        <BlockTool title={display()} part={props.part}>
          <Show when={diffSummary()}>
            <text fg={theme.textMuted}>⎿  {diffSummary()}</text>
          </Show>
          <box paddingLeft={1}>
            <diff
              diff={diffContent()}
              view={view()}
              filetype={ft()}
              syntaxStyle={syntax()}
              showLineNumbers={true}
              width="100%"
              wrapMode={ctx.diffWrapMode()}
              fg={theme.text}
              addedBg={theme.diffAddedBg}
              removedBg={theme.diffRemovedBg}
              contextBg={theme.diffContextBg}
              addedSignColor={theme.diffHighlightAdded}
              removedSignColor={theme.diffHighlightRemoved}
              lineNumberFg={theme.diffLineNumber}
              lineNumberBg={theme.diffContextBg}
              addedLineNumberBg={theme.diffAddedLineNumberBg}
              removedLineNumberBg={theme.diffRemovedLineNumberBg}
            />
          </box>
          <Diagnostics diagnostics={props.metadata.diagnostics} filePath={fp() ?? ""} />
        </BlockTool>
      </Match>
      <Match when={true}>
        <InlineTool icon="←" pending="Preparing edit..." complete={fp()} part={props.part} outputPreview={diffSummary()}>
          {display()} {replAll() ? "[replace_all]" : ""}
        </InlineTool>
      </Match>
    </Switch>
  )
}

function ApplyPatch(props: ToolProps<typeof ApplyPatchTool>) {
  const ctx = use()
  const { theme, syntax } = useTheme()

  const files = createMemo(() => props.metadata.files ?? [])

  const view = createMemo(() => {
    const diffStyle = ctx.tui.diff_style
    if (diffStyle === "stacked") return "unified"
    return ctx.width > 120 ? "split" : "unified"
  })

  function Diff(p: { diff: string; filePath: string }) {
    return (
      <box paddingLeft={1}>
        <diff
          diff={p.diff}
          view={view()}
          filetype={filetype(p.filePath)}
          syntaxStyle={syntax()}
          showLineNumbers={true}
          width="100%"
          wrapMode={ctx.diffWrapMode()}
          fg={theme.text}
          addedBg={theme.diffAddedBg}
          removedBg={theme.diffRemovedBg}
          contextBg={theme.diffContextBg}
          addedSignColor={theme.diffHighlightAdded}
          removedSignColor={theme.diffHighlightRemoved}
          lineNumberFg={theme.diffLineNumber}
          lineNumberBg={theme.diffContextBg}
          addedLineNumberBg={theme.diffAddedLineNumberBg}
          removedLineNumberBg={theme.diffRemovedLineNumberBg}
        />
      </box>
    )
  }

  function title(file: { type: string; relativePath: string; filePath: string; deletions: number }) {
    if (file.type === "delete") return "# Deleted " + file.relativePath
    if (file.type === "add") return "# Created " + file.relativePath
    if (file.type === "move") return "# Moved " + normalizePath(file.filePath) + " → " + file.relativePath
    return "← Patched " + file.relativePath
  }

  return (
    <Switch>
      <Match when={files().length > 0}>
        <For each={files()}>
          {(file) => (
            <BlockTool title={title(file)} part={props.part}>
              <Show
                when={file.type !== "delete"}
                fallback={
                  <text fg={theme.diffRemoved}>
                    -{file.deletions} line{file.deletions !== 1 ? "s" : ""}
                  </text>
                }
              >
                <Diff diff={file.diff} filePath={file.filePath} />
                <Diagnostics diagnostics={props.metadata.diagnostics} filePath={file.movePath ?? file.filePath} />
              </Show>
            </BlockTool>
          )}
        </For>
      </Match>
      <Match when={true}>
        <InlineTool icon="%" pending="Preparing patch..." complete={false} part={props.part}>
          Patch
        </InlineTool>
      </Match>
    </Switch>
  )
}

function TodoWrite(props: ToolProps<typeof TodoWriteTool>) {
  const { theme } = useTheme()
  // Use input todos (always available once tool starts) with metadata as fallback
  const todos = createMemo(() => {
    const metaTodos = props.metadata.todos as any[] | undefined
    const inputTodos = props.input.todos
    return metaTodos?.length ? metaTodos : inputTodos ?? []
  })
  const hasTodos = createMemo(() => todos().length > 0)
  const score = createMemo(() => {
    const t = todos()
    const done = t.filter((x: any) => x.status === "completed").length
    return `${done}/${t.length} completed`
  })

  return (
    <Switch>
      <Match when={hasTodos()}>
        <box flexDirection="column" marginTop={1}>
          <text fg={theme.textMuted}>{"─".repeat(40)}</text>
          <box flexDirection="row" gap={1} paddingLeft={1}>
            <text fg={theme.text}><span style={{ bold: true }}>Todos</span></text>
            <text fg={theme.textMuted}>{score()}</text>
          </box>
          <box flexDirection="column" paddingLeft={1} paddingTop={1}>
            <For each={todos()}>
              {(todo: any) => <TodoItem status={todo.status} content={todo.content} />}
            </For>
          </box>
        </box>
      </Match>
      <Match when={true}>
        <InlineTool icon="☐" pending="Updating todos..." complete={false} part={props.part}>
          Updating todos...
        </InlineTool>
      </Match>
    </Switch>
  )
}

function TodoRead(props: ToolProps<any>) {
  const { theme } = useTheme()
  const todos = createMemo(() => {
    const metaTodos = (props.metadata as any).todos as any[] | undefined
    if (metaTodos?.length) return metaTodos
    // Fallback: parse from output JSON
    if (props.output) {
      try {
        const parsed = JSON.parse(props.output)
        if (Array.isArray(parsed)) return parsed
      } catch {
        // not JSON
      }
    }
    return []
  })
  const score = createMemo(() => {
    const t = todos()
    const done = t.filter((x: any) => x.status === "completed").length
    return `${done}/${t.length} completed`
  })

  return (
    <Switch>
      <Match when={todos().length > 0}>
        <box flexDirection="column" marginTop={1}>
          <text fg={theme.textMuted}>{"─".repeat(40)}</text>
          <box flexDirection="row" gap={1} paddingLeft={1}>
            <text fg={theme.text}><span style={{ bold: true }}>Todos</span></text>
            <text fg={theme.textMuted}>{score()}</text>
          </box>
          <box flexDirection="column" paddingLeft={1} paddingTop={1}>
            <For each={todos()}>
              {(todo: any) => <TodoItem status={todo.status} content={todo.content} />}
            </For>
          </box>
        </box>
      </Match>
      <Match when={true}>
        <InlineTool icon="☐" pending="Reading todos..." complete={`${todos().length} todos`} part={props.part}>
          Read todos
        </InlineTool>
      </Match>
    </Switch>
  )
}

function Question(props: ToolProps<typeof QuestionTool>) {
  const { theme } = useTheme()
  const count = createMemo(() => props.input.questions?.length ?? 0)

  function format(answer?: string[]) {
    if (!answer?.length) return "(no answer)"
    return answer.join(", ")
  }

  return (
    <Switch>
      <Match when={props.metadata.answers}>
        <BlockTool title="# Questions" part={props.part}>
          <box gap={1}>
            <For each={props.input.questions ?? []}>
              {(q, i) => (
                <box flexDirection="column">
                  <text fg={theme.textMuted}>{q.question}</text>
                  <text fg={theme.text}>{format(props.metadata.answers?.[i()])}</text>
                </box>
              )}
            </For>
          </box>
        </BlockTool>
      </Match>
      <Match when={true}>
        <InlineTool icon="→" pending="Asking questions..." complete={count()} part={props.part}>
          Asked {count()} question{count() !== 1 ? "s" : ""}
        </InlineTool>
      </Match>
    </Switch>
  )
}

function Skill(props: ToolProps<typeof SkillTool>) {
  return (
    <InlineTool icon="→" pending="Loading skill..." complete={props.input.name} part={props.part}>
      Skill({props.input.name ? JSON.stringify(props.input.name) : ""})
    </InlineTool>
  )
}

function MultiEdit(props: ToolProps<any>) {
  const ctx = use()
  const { theme, syntax } = useTheme()
  const inp = props.input as any
  const fp = () => inp.filePath ?? inp.file_path
  const editCount = createMemo(() => inp.edits?.length ?? 0)

  const view = createMemo(() => {
    const diffStyle = ctx.tui.diff_style
    if (diffStyle === "stacked") return "unified"
    return ctx.width > 120 ? "split" : "unified"
  })

  const lastDiff = createMemo(() => {
    const results = props.metadata.results as any[] | undefined
    if (!results?.length) return undefined
    // Find the last result that has a diff
    for (let i = results.length - 1; i >= 0; i--) {
      if (results[i]?.diff) return results[i].diff
    }
    return undefined
  })

  const display = createMemo(() => {
    const filePath = fp()
    if (!filePath) return `MultiEdit()`
    return `MultiEdit(${normalizePath(filePath)}) [${editCount()} edits]`
  })

  return (
    <Switch>
      <Match when={lastDiff()}>
        <BlockTool title={display()} part={props.part}>
          <box paddingLeft={1}>
            <diff
              diff={lastDiff()}
              view={view()}
              filetype={filetype(fp())}
              syntaxStyle={syntax()}
              showLineNumbers={true}
              width="100%"
              wrapMode={ctx.diffWrapMode()}
              fg={theme.text}
              addedBg={theme.diffAddedBg}
              removedBg={theme.diffRemovedBg}
              contextBg={theme.diffContextBg}
              addedSignColor={theme.diffHighlightAdded}
              removedSignColor={theme.diffHighlightRemoved}
              lineNumberFg={theme.diffLineNumber}
              lineNumberBg={theme.diffContextBg}
              addedLineNumberBg={theme.diffAddedLineNumberBg}
              removedLineNumberBg={theme.diffRemovedLineNumberBg}
            />
          </box>
        </BlockTool>
      </Match>
      <Match when={true}>
        <InlineTool icon="←" pending="Preparing multi-edit..." complete={fp()} part={props.part}>
          {display()}
        </InlineTool>
      </Match>
    </Switch>
  )
}

function PlanExit(props: ToolProps<any>) {
  return (
    <InlineTool icon="⏎" pending="Exiting plan mode..." complete="Exited plan mode" part={props.part}>
      PlanExit()
    </InlineTool>
  )
}

function Invalid(props: ToolProps<any>) {
  const { theme } = useTheme()
  return (
    <InlineTool icon="⚠" iconColor={theme.error} pending="Invalid tool call" complete="Invalid tool call" part={props.part} outputPreview={props.output}>
      Invalid tool call
    </InlineTool>
  )
}

function BatchTool(props: ToolProps<any>) {
  const inp = props.input as any
  const count = createMemo(() => {
    const ops = inp.operations ?? inp.tools ?? []
    return Array.isArray(ops) ? ops.length : 0
  })

  return (
    <InlineTool icon="⚙" pending="Running batch..." complete={`${count()} operations`} part={props.part}>
      Batch({count()} operations)
    </InlineTool>
  )
}

function LspTool(props: ToolProps<any>) {
  const inp = props.input as any
  const method = () => inp.method ?? inp.action ?? "query"

  return (
    <InlineTool icon="◇" pending={`LSP ${method()}...`} complete={method()} part={props.part}>
      LSP({method()})
    </InlineTool>
  )
}

function Diagnostics(props: { diagnostics?: Record<string, Record<string, any>[]>; filePath: string }) {
  const { theme } = useTheme()
  const errors = createMemo(() => {
    const normalized = Filesystem.normalizePath(props.filePath)
    const arr = props.diagnostics?.[normalized] ?? []
    return arr.filter((x) => x.severity === 1).slice(0, 3)
  })

  return (
    <Show when={errors().length}>
      <box>
        <For each={errors()}>
          {(diagnostic) => (
            <text fg={theme.error}>
              Error [{diagnostic.range.start.line + 1}:{diagnostic.range.start.character + 1}] {diagnostic.message}
            </text>
          )}
        </For>
      </box>
    </Show>
  )
}

function normalizePath(input?: string) {
  if (!input) return ""

  const cwd = process.cwd()
  const absolute = path.isAbsolute(input) ? input : path.resolve(cwd, input)
  const relative = path.relative(cwd, absolute)

  if (!relative) return "."
  if (!relative.startsWith("..")) return relative

  // outside cwd - use absolute
  return absolute
}

function input(input: Record<string, any>, omit?: string[]): string {
  const primitives = Object.entries(input).filter(([key, value]) => {
    if (omit?.includes(key)) return false
    return typeof value === "string" || typeof value === "number" || typeof value === "boolean"
  })
  if (primitives.length === 0) return ""
  return `[${primitives.map(([key, value]) => `${key}=${value}`).join(", ")}]`
}

/** Format tool call in function-call style: ToolName("arg") or ToolName({"key":"val"}) */
function formatToolCall(name: string, args: Record<string, any>, primaryKey?: string): string {
  if (primaryKey && args[primaryKey] !== undefined) {
    return `${name}(${JSON.stringify(args[primaryKey])})`
  }
  const entries = Object.entries(args).filter(
    ([, v]) => typeof v === "string" || typeof v === "number" || typeof v === "boolean",
  )
  if (entries.length === 0) return `${name}()`
  if (entries.length === 1) return `${name}(${JSON.stringify(entries[0][1])})`
  const json = JSON.stringify(Object.fromEntries(entries))
  const maxLen = 120
  return json.length > maxLen ? `${name}(${json.slice(0, maxLen - 3)}...)` : `${name}(${json})`
}

function filetype(input?: string) {
  if (!input) return "none"
  const ext = path.extname(input)
  const language = LANGUAGE_EXTENSIONS[ext]
  if (["typescriptreact", "javascriptreact", "javascript"].includes(language)) return "typescript"
  return language
}
