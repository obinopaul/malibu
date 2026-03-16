"""Tests for malibu.agent.prompts — system prompt building."""

from __future__ import annotations

from malibu.agent.prompts import build_system_prompt


class TestBuildSystemPrompt:
    def test_contains_cwd(self):
        prompt = build_system_prompt(cwd="/home/user/project", mode="accept_edits")
        assert "/home/user/project" in prompt

    def test_contains_mode(self):
        prompt = build_system_prompt(cwd=".", mode="accept_edits")
        assert "accept_edits" in prompt

    def test_ask_before_edits_addendum(self):
        prompt = build_system_prompt(cwd=".", mode="ask_before_edits")
        assert "Ask Before Edits" in prompt
        assert "approval" in prompt.lower()

    def test_accept_edits_addendum(self):
        prompt = build_system_prompt(cwd=".", mode="accept_edits")
        assert "Accept Edits" in prompt

    def test_accept_everything_addendum(self):
        prompt = build_system_prompt(cwd=".", mode="accept_everything")
        assert "Accept Everything" in prompt
        assert "auto-approved" in prompt.lower()

    def test_unknown_mode_no_addendum(self):
        prompt = build_system_prompt(cwd=".", mode="custom_mode")
        # Should have base prompt but no mode addendum
        assert "Malibu" in prompt
        assert "custom_mode" in prompt

    def test_extra_context_appended(self):
        prompt = build_system_prompt(cwd=".", mode="accept_edits", extra_context="Use TypeScript only.")
        assert "Use TypeScript only." in prompt
        assert "Additional Context" in prompt

    def test_no_extra_context(self):
        prompt = build_system_prompt(cwd=".", mode="accept_edits", extra_context=None)
        assert "Additional Context" not in prompt

    def test_prompt_includes_capabilities(self):
        prompt = build_system_prompt(cwd=".", mode="accept_edits")
        assert "Read, write, and edit files" in prompt
        assert "Execute shell commands" in prompt
