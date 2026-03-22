"""Tests for malibu.client.session_display module."""

from __future__ import annotations

from acp.schema import (
    AgentMessageChunk,
    ConfigOptionUpdate,
    SessionConfigOption,
    SessionConfigOptionSelect,
    SessionConfigSelectOption,
    TextContentBlock,
    ToolCallStart,
)

from malibu.client.session_display import display_session_update


def test_display_agent_message(capsys):
    update = AgentMessageChunk(
        content=TextContentBlock(type="text", text="Hello!"),
        session_update="agent_message_chunk",
    )
    display_session_update("sess-1", update)
    captured = capsys.readouterr()
    assert "Hello!" in captured.out


def test_display_tool_call_start(capsys):
    update = ToolCallStart(
        tool_call_id="call-1",
        title="Reading file",
        kind="read",
        status="pending",
        session_update="tool_call",
    )
    display_session_update("sess-1", update)
    captured = capsys.readouterr()
    assert "Reading file" in captured.out


def test_display_config_option_update(capsys):
    """ConfigOptionUpdate uses config_options list, not config_id/value."""
    update = ConfigOptionUpdate(
        session_update="config_option_update",
        config_options=[
            SessionConfigOption(
                root=SessionConfigOptionSelect(
                    id="llm_model",
                    name="Model",
                    type="select",
                    current_value="gpt-4o",
                    options=[
                        SessionConfigSelectOption(name="GPT-4o", value="gpt-4o"),
                        SessionConfigSelectOption(name="GPT-4o mini", value="gpt-4o-mini"),
                    ],
                )
            ),
        ],
    )
    display_session_update("sess-1", update)
    captured = capsys.readouterr()
    assert "llm_model" in captured.out
    assert "gpt-4o" in captured.out
