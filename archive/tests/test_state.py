"""Tests for malibu.agent.state — SessionMeta dataclass."""

from __future__ import annotations

from malibu.agent.state import SessionMeta


class TestSessionMeta:
    def test_basic_construction(self):
        meta = SessionMeta(session_id="s1", cwd="/work")
        assert meta.session_id == "s1"
        assert meta.cwd == "/work"
        assert meta.mode == "accept_edits"
        assert meta.model == "openai:gpt-4o"
        assert meta.todos == []

    def test_custom_values(self):
        meta = SessionMeta(
            session_id="s2",
            cwd="/project",
            mode="accept_everything",
            model="anthropic:claude-sonnet-4-5",
            todos=[{"content": "Do stuff", "status": "pending"}],
        )
        assert meta.mode == "accept_everything"
        assert meta.model == "anthropic:claude-sonnet-4-5"
        assert len(meta.todos) == 1

    def test_todos_default_is_independent(self):
        m1 = SessionMeta(session_id="a", cwd=".")
        m2 = SessionMeta(session_id="b", cwd=".")
        m1.todos.append({"content": "task"})
        assert m2.todos == []
