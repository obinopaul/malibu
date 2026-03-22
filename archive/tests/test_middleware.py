"""Tests for malibu.agent.middleware — local context loading and middleware stack."""

from __future__ import annotations

from pathlib import Path

from malibu.agent.middleware import _CONTEXT_FILES, build_middleware_stack, load_local_context


class TestLoadLocalContext:
    def test_no_context_files(self, tmp_path: Path):
        result = load_local_context(str(tmp_path))
        assert result is None

    def test_agents_md(self, tmp_path: Path):
        (tmp_path / "AGENTS.md").write_text("# Project rules\nUse Python.\n", encoding="utf-8")
        result = load_local_context(str(tmp_path))
        assert result is not None
        assert "Project rules" in result
        assert "AGENTS.md" in result

    def test_malibu_context_file(self, tmp_path: Path):
        ctx_dir = tmp_path / ".malibu"
        ctx_dir.mkdir()
        (ctx_dir / "context.md").write_text("Custom context here.", encoding="utf-8")
        result = load_local_context(str(tmp_path))
        assert "Custom context here." in result

    def test_multiple_context_files(self, tmp_path: Path):
        (tmp_path / "AGENTS.md").write_text("agents content", encoding="utf-8")
        ctx_dir = tmp_path / ".malibu"
        ctx_dir.mkdir()
        (ctx_dir / "context.md").write_text("context content", encoding="utf-8")
        (ctx_dir / "instructions.md").write_text("instructions content", encoding="utf-8")
        result = load_local_context(str(tmp_path))
        assert "agents content" in result
        assert "context content" in result
        assert "instructions content" in result

    def test_context_files_constant(self):
        assert ".malibu/context.md" in _CONTEXT_FILES
        assert "AGENTS.md" in _CONTEXT_FILES


class TestBuildMiddlewareStack:
    def test_accept_everything_includes_logger_only(self):
        stack = build_middleware_stack("accept_everything")
        # No HITL middleware, but logger is always added
        assert len(stack) == 1

    def test_ask_before_edits_includes_hitl(self):
        stack = build_middleware_stack("ask_before_edits")
        assert len(stack) == 2  # HITL + logger

    def test_accept_edits_includes_hitl(self):
        stack = build_middleware_stack("accept_edits")
        assert len(stack) == 2  # HITL + logger
