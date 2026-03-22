"""Tests for malibu.config module."""

from __future__ import annotations

from pathlib import Path
import sys
import types

from malibu.config import Settings


def test_settings_defaults(monkeypatch):
    """Settings should use env defaults when nothing is set."""
    monkeypatch.delenv("LLM_MODEL", raising=False)
    s = Settings(
        database_url="sqlite+aiosqlite:///test.db",
        jwt_secret="test-secret",
        llm_api_key="sk-test",
        _env_file=None,
    )
    assert s.llm_model == "openai:gpt-5.4"
    assert s.max_file_size == 10_485_760
    assert s.log_level == "INFO"
    assert s.agent_tool_profile == "core"


def test_resolve_allowed_paths():
    """resolve_allowed_paths should return absolute paths."""
    s = Settings(
        database_url="sqlite+aiosqlite:///test.db",
        jwt_secret="test-secret",
        llm_api_key="sk-test",
        allowed_paths=[".", "/tmp"],
    )
    cwd = "/home/user/project"
    paths = s.resolve_allowed_paths(cwd)
    assert all(isinstance(p, Path) for p in paths)
    assert all(p.is_absolute() for p in paths)


def test_settings_custom_values():
    """Settings should accept and store custom values."""
    s = Settings(
        database_url="postgresql+asyncpg://user:pass@host/db",
        jwt_secret="my-secret",
        llm_model="anthropic:claude-sonnet-4-20250514",
        llm_api_key="sk-ant-test",
        max_file_size=500_000,
    )
    assert s.llm_model == "anthropic:claude-sonnet-4-20250514"
    assert s.max_file_size == 500_000


def test_create_llm_caches_by_resolved_model(monkeypatch):
    openai_module = types.ModuleType("langchain_openai")

    class FakeChatOpenAI:
        init_calls: list[dict[str, str]] = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            type(self).init_calls.append(kwargs)

    openai_module.ChatOpenAI = FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", openai_module)

    settings = Settings(
        database_url="sqlite+aiosqlite:///test.db",
        jwt_secret="test-secret",
        llm_api_key="sk-test",
        llm_base_url="https://example.invalid/v1",
        _env_file=None,
    )

    first = settings.create_llm("openai:gpt-5.4")
    second = settings.create_llm("openai:gpt-5.4")
    third = settings.create_llm("openai:gpt-4o-mini")

    assert first is second
    assert third is not first
    assert FakeChatOpenAI.init_calls == [
        {
            "model": "gpt-5.4",
            "api_key": "sk-test",
            "base_url": "https://example.invalid/v1",
        },
        {
            "model": "gpt-4o-mini",
            "api_key": "sk-test",
            "base_url": "https://example.invalid/v1",
        },
    ]
