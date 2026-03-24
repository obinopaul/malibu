import { useTheme } from "../context/theme"
import { TextAttributes } from "@opentui/core"

export interface TodoItemProps {
  status: string
  content: string
}

export function TodoItem(props: TodoItemProps) {
  const { theme } = useTheme()

  const icon = () => {
    switch (props.status) {
      case "completed":
        return "✓"
      case "in_progress":
        return "»"
      case "cancelled":
        return "✗"
      default:
        return "☐"
    }
  }

  const iconColor = () => {
    switch (props.status) {
      case "completed":
        return theme.success
      case "in_progress":
        return theme.accent
      case "cancelled":
        return theme.error
      default:
        return theme.textMuted
    }
  }

  const textColor = () => {
    switch (props.status) {
      case "in_progress":
        return theme.text
      case "cancelled":
        return theme.error
      default:
        return theme.textMuted
    }
  }

  const strikethrough = () => props.status === "cancelled"

  return (
    <box flexDirection="row" gap={1}>
      <text
        flexShrink={0}
        fg={iconColor()}
      >
        {icon()}
      </text>
      <text
        flexGrow={1}
        wrapMode="word"
        fg={textColor()}
        attributes={strikethrough() ? TextAttributes.STRIKETHROUGH : undefined}
      >
        {props.content}
      </text>
    </box>
  )
}
