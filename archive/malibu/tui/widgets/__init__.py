"""Reusable widgets for Malibu's Textual shell."""

from malibu.tui.widgets.activity_strip import ActivityStrip
from malibu.tui.widgets.autocomplete_popup import AutocompletePopup
from malibu.tui.widgets.chat_input import ChatInput, ChatTextArea
from malibu.tui.widgets.conversation import ConversationLog
from malibu.tui.widgets.message_list import MessageList
from malibu.tui.widgets.mcp_viewer import McpViewerModal
from malibu.tui.widgets.plan_panel import PlanPanel
from malibu.tui.widgets.spinner import SpinnerWidget
from malibu.tui.widgets.status_bar import StatusBar
from malibu.tui.widgets.tool_renderers import ToolRendererRegistry

__all__ = [
    "ActivityStrip",
    "AutocompletePopup",
    "ChatInput",
    "ChatTextArea",
    "ConversationLog",
    "McpViewerModal",
    "MessageList",
    "PlanPanel",
    "SpinnerWidget",
    "StatusBar",
    "ToolRendererRegistry",
]
