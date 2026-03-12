"""Tests for malibu.config — Settings configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from malibu.config import Settings, get_settings


class TestSettingsDefaults:
    def test_default_values(self):
        s = Settings(
            database_url="sqlite+aiosqlite:///test.db",
            jwt_secret="secret",
            llm_model="openai:gpt-4o",
            _env_file=None,
        )
        assert s.jwt_algorithm == "HS256"
        assert s.jwt_expiry_hours == 24
        assert s.max_file_size == 10 * 1024 * 1024
        assert s.otel_enabled is False
        assert s.api_port == 8000

    def test_allowed_paths_default_empty(self, monkeypatch):
        monkeypatch.delenv("ALLOWED_PATHS", raising=False)
        s = Settings(
            database_url="sqlite:///x",
            jwt_secret="s",
            llm_model="openai:gpt-4o",
            _env_file=None,
        )
        assert s.allowed_paths == []


class TestResolveAllowedPaths:
    def test_with_allowed_paths(self, tmp_path: Path):
        s = Settings(
            database_url="sqlite:///x",
            jwt_secret="s",
            llm_model="openai:gpt-4o",
            allowed_paths=[str(tmp_path)],
        )
        resolved = s.resolve_allowed_paths("/fallback")
        assert resolved == [tmp_path.resolve()]

    def test_fallback_to_cwd(self, tmp_path: Path):
        s = Settings(
            database_url="sqlite:///x",
            jwt_secret="s",
            llm_model="openai:gpt-4o",
            allowed_paths=[],
        )
        resolved = s.resolve_allowed_paths(str(tmp_path))
        assert resolved == [tmp_path.resolve()]


class TestCreateLLM:
    def test_openai_model_string(self):
        s = Settings(
            database_url="sqlite:///x",
            jwt_secret="s",
            llm_model="openai:gpt-4o",
            llm_api_key="sk-test",
        )
        # Just verify it produces a ChatModel without error
        llm = s.create_llm()
        assert llm is not None

    def test_model_without_provider_prefix(self):
        s = Settings(
            database_url="sqlite:///x",
            jwt_secret="s",
            llm_model="gpt-4o-mini",
            llm_api_key="sk-test",
        )
        llm = s.create_llm()
        assert llm is not None


class TestGetSettings:
    def test_creates_settings_instance(self):
        s = get_settings()
        assert isinstance(s, Settings)
