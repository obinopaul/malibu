"""Backward-compatible export of the new conversation log."""

from malibu.tui.widgets.conversation.log import ConversationLog as MessageList

__all__ = ["MessageList"]
