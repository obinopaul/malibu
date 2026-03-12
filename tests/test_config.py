"""Tests for malibu.config module."""

from __future__ import annotations

from pathlib import Path

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
    assert s.llm_model == "openai:gpt-4o"
    assert s.max_file_size == 10_485_760
    assert s.log_level == "INFO"


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
