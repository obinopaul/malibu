from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _disable_langsmith(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)


@pytest.fixture
def tmp_path() -> Path:
    base_dir = Path.cwd() / ".pytest_tmp"
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"case-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
