"""Shared test fixtures for Malibu test suite."""

from __future__ import annotations

import asyncio
from typing import Any, Literal
from unittest.mock import AsyncMock, MagicMock

import pytest

from malibu.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Return a test Settings instance with defaults overridden."""
    return Settings(
        database_url="sqlite+aiosqlite:///test.db",
        jwt_secret="test-secret-key-for-tests-only",
        llm_model="openai:gpt-4o-mini",
        llm_api_key="sk-test-key",
        allowed_paths=["."],
        max_file_size=1_000_000,
        log_level="DEBUG",
    )


@pytest.fixture
def mock_client() -> MagicMock:
    """Return a mock ACP Client."""
    client = MagicMock()
    client.session_update = AsyncMock()
    client.request_permission = AsyncMock()
    client.write_text_file = AsyncMock()
    client.read_text_file = AsyncMock()
    return client
