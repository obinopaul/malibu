"""Backward-compatible exports for conversation blocks."""

from malibu.tui.widgets.conversation.blocks import (
    AssistantMessageBlock as AssistantMessage,
    SystemMessageBlock as BaseMessage,
    SystemMessageBlock as ErrorMessage,
    ThoughtMessageBlock as ThoughtMessage,
    ToolCallBlock as ToolCallMessage,
    UserMessageBlock as UserMessage,
)

PlanEntryMessage = SystemMessageBlock = BaseMessage

__all__ = [
    "AssistantMessage",
    "BaseMessage",
    "ErrorMessage",
    "PlanEntryMessage",
    "ThoughtMessage",
    "ToolCallMessage",
    "UserMessage",
]
